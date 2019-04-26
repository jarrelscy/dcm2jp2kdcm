import argparse
import collections
import json
import requests
import os
import glob
import sys
import subprocess
import time
import zipfile
import tempfile
import shutil
from shutil import copy as fileCopy
import pydicom
import code
import glymur
glymur.set_option('lib.num_threads', 32)
from collections import OrderedDict
import requests.packages.urllib3
import numpy as np
import traceback
requests.packages.urllib3.disable_warnings()


def cleanServer(server):
    server.strip()
    if server[-1] == '/':
        server = server[:-1]
    if server.find('http') == -1:
        server = 'https://' + server
    return server


def isTrue(arg):
    return arg is not None and (arg == 'Y' or arg == '1' or arg == 'True')


def download(name, pathDict):
    if os.access(pathDict['absolutePath'], os.R_OK):
        try:
            os.symlink(pathDict['absolutePath'], name)
        except:
            fileCopy(pathDict['absolutePath'], name)
            print ('Copied %s.' % pathDict['absolutePath'])
    else:
        with open(name, 'wb') as f:
            r = get(pathDict['URI'], stream=True)

            for block in r.iter_content(1024):
                if not block:
                    break

                f.write(block)
        print ('Downloaded file %s.' % name)

def zipdir(dirPath=None, zipFilePath=None, includeDirInZip=True):
    if not zipFilePath:
        zipFilePath = dirPath + ".zip"
    if not os.path.isdir(dirPath):
        raise OSError("dirPath argument must point to a directory. "
            "'%s' does not." % dirPath)
    parentDir, dirToZip = os.path.split(dirPath)
    def trimPath(path):
        archivePath = path.replace(parentDir, "", 1)
        if parentDir:
            archivePath = archivePath.replace(os.path.sep, "", 1)
        if not includeDirInZip:
            archivePath = archivePath.replace(dirToZip + os.path.sep, "", 1)
        return os.path.normcase(archivePath)
    outFile = zipfile.ZipFile(zipFilePath, "w",
        compression=zipfile.ZIP_DEFLATED)
    for (archiveDirPath, dirNames, fileNames) in os.walk(dirPath):
        for fileName in fileNames:
            filePath = os.path.join(archiveDirPath, fileName)
            outFile.write(filePath, trimPath(filePath))
        # Make sure we get empty directories as well
        if not fileNames and not dirNames:
            zipInfo = zipfile.ZipInfo(trimPath(archiveDirPath) + "/")
            # some web sites suggest doing
            # zipInfo.external_attr = 16
            # or
            # zipInfo.external_attr = 48
            # Here to allow for inserting an empty directory.  Still TBD/TODO.
            outFile.writestr(zipInfo, "")
    outFile.close()


parser = argparse.ArgumentParser(description="Run dcm2niix on every file in a session")
parser.add_argument("--host", default="http://ahmldicom01.baysidehealth.intra", help="XNAT host", required=True)
parser.add_argument("--user", help="XNAT username", required=True)
parser.add_argument("--password", help="Password", required=True)
parser.add_argument("--session", help="Session ID", required=True)
parser.add_argument("--subject", help="Subject Label", required=False)
parser.add_argument("--project", help="Project", required=False)
parser.add_argument("--dicomdir", help="Root output directory for DICOM files", required=True)
parser.add_argument("--compress", help="Compress DICOM files into jp2k, else decompress", required=True)
parser.add_argument("--upload-by-ref", help="Upload \"by reference\". Only use if your host can read your file system.")
parser.add_argument("--workflowId", help="Pipeline workflow ID")
parser.add_argument('--version', action='version', version='%(prog)s 1')

args, unknown_args = parser.parse_known_args()
host = cleanServer(args.host)
session = args.session
subject = args.subject
project = args.project
compress = isTrue(args.compress)
dicomdir = args.dicomdir
outputdir = dicomdir+'-output'
workflowId = args.workflowId
uploadByRef = isTrue(args.upload_by_ref)
dcm2niixArgs = unknown_args if unknown_args is not None else []

#imgdir = niftidir + "/IMG"
#bidsdir = niftidir + "/BIDS"

builddir = os.getcwd()

# Set up working directory
if not os.access(dicomdir, os.R_OK):
    print ('Making DICOM directory %s' % dicomdir)
    os.mkdir(dicomdir)
# Set up working directory
if not os.access(outputdir, os.R_OK):
    print ('Making output DICOM directory %s' % outputdir)
    os.mkdir(outputdir)

# Set up session
sess = requests.Session()
sess.verify = False
sess.auth = (args.user, args.password)


def get(url, **kwargs):
    try:
        r = sess.get(url, **kwargs)
        r.raise_for_status()
    except (requests.ConnectionError, requests.exceptions.RequestException) as e:
        print ("Request Failed")
        print ("    " + str(e))
        sys.exit(1)
    return r

if project is None or subject is None:
    # Get project ID and subject ID from session JSON
    print ("Get project and subject ID for session ID %s." % session)
    r = get(host + "/data/experiments/%s" % session, params={"format": "json", "handler": "values", "columns": "project,subject_ID"})
    sessionValuesJson = r.json()["ResultSet"]["Result"][0]
    project = sessionValuesJson["project"] if project is None else project
    subjectID = sessionValuesJson["subject_ID"]
    print ("Project: " + project)
    print ("Subject ID: " + subjectID)

    if subject is None:
        print ("Get subject label for subject ID %s." % subjectID)
        r = get(host + "/data/subjects/%s" % subjectID, params={"format": "json", "handler": "values", "columns": "label"})
        subject = r.json()["ResultSet"]["Result"][0]["label"]
        print ("Subject label: " + subject)

# Get list of scan ids
print ("Get scan list for session ID %s." % session)
r = get(host + "/data/experiments/%s/scans" % session, params={"format": "json"})
scanRequestResultList = r.json()["ResultSet"]["Result"]
scanIDList = [scan['ID'] for scan in scanRequestResultList]
seriesDescList = [scan['series_description'] for scan in scanRequestResultList]  # { id: sd for (scan['ID'], scan['series_description']) in scanRequestResultList }
print ('Found scans %s.' % ', '.join(scanIDList))
print ('Series descriptions %s' % ', '.join(seriesDescList))

# Fall back on scan type if series description field is empty
if set(seriesDescList) == set(['']):
    seriesDescList = [scan['type'] for scan in scanRequestResultList]
    print ('Fell back to scan types %s' % ', '.join(seriesDescList))


# Cheat and reverse scanid and seriesdesc lists so numbering is in the right order
for scanid, seriesdesc in zip(reversed(scanIDList), reversed(seriesDescList)):
    print ('Beginning process for scan %s.' % scanid)
    os.chdir(builddir)


    # Get scan resources
    print ("Get scan resources for scan %s." % scanid)
    r = get(host + "/data/experiments/%s/scans/%s/resources" % (session, scanid), params={"format": "json"})
    scanResources = r.json()["ResultSet"]["Result"]
    print ('Found resources %s.' % ', '.join(res["label"] for res in scanResources))


    ##########
    # Prepare DICOM directory structure
    scanDicomDir = os.path.join(dicomdir, scanid)
    if not os.path.isdir(scanDicomDir):
        print ('Making scan DICOM directory %s.' % scanDicomDir)
        os.mkdir(scanDicomDir)
        
    
        
    # Remove any existing files in the builddir.
    # This is unlikely to happen in any environment other than testing.
    for f in os.listdir(scanDicomDir):
        os.remove(os.path.join(scanDicomDir, f))

    ##########
    # Get list of DICOMs

    # Deal with DICOMs
    print ('Get list of DICOM files for scan %s.' % scanid)

    filesURL = host + "/data/experiments/%s/scans/%s/resources/DICOM%s/files" % (session, scanid, '_COMPRESSED' if not compress else '')
    

    r = get(filesURL, params={"format": "json"})
    # I don't like the results being in a list, so I will build a dict keyed off file name
    dicomFileDict = {dicom['Name']: {'URI': host + dicom['URI']} for dicom in r.json()["ResultSet"]["Result"]}

    # Have to manually add absolutePath with a separate request
    r = get(filesURL, params={"format": "json", "locator": "absolutePath"})
    for dicom in r.json()["ResultSet"]["Result"]:
        dicomFileDict[dicom['Name']]['absolutePath'] = dicom['absolutePath']

    ##########
    # Download DICOMs
    print ("Downloading files for scan %s." % scanid)
    os.chdir(scanDicomDir)

    # Check secondary
    # Download any one DICOM from the series and check its headers
    # If the headers indicate it is a secondary capture, we will skip this series.
    dicomFileList = dicomFileDict.items()

    ##########
    for name, pathDict in dicomFileList:
        download(name, pathDict)

    os.chdir(builddir)
    print ('Done downloading for scan %s.' % scanid)
    print ('Downloaded files:')
    print ('\n'.join(os.listdir(scanDicomDir)))

    ##########
    # Upload results
    print ('Preparing to upload files for scan %s.' % scanid)

    # We should delete the existing DICOM resource.
    
        
    try:
        # Prepare output DICOM directory structure
        scanOutputDicomDir = os.path.join(outputdir, scanid)
        shutil.copytree(scanDicomDir, scanOutputDicomDir)
        passed = True
        for root, dirs, files in os.walk(scanOutputDicomDir, topdown=False):
            for name in files:
                try:
                    file = os.path.join(root, name)
                    print (file, compress)
                    if compress:
                        with tempfile.NamedTemporaryFile() as f:    
                            ds = pydicom.read_file(file)
                            if np.min(ds.pixel_array) < 0:
                                add = -np.min(ds.pixel_array)
                                ds.pixel_array += add
                                ds.RescaleIntercept -= add
                                
                            
                            type, bitsstored = (np.uint16, 16) if int(ds.BitsStored) > 8 else (np.uint8, 8)
                            ds.BitsStored = bitsstored
                            ds.BitsAllocated = bitsstored
                            glymur.Jp2k(f.name, ds.pixel_array.astype(type))
                            f.seek(0)
                            ds.PixelData = pydicom.encaps.encapsulate(list(pydicom.encaps.fragment_frame(f.read())))
                            ds[(0x7FE0,0x0010)].VR = 'OB' #encapsulated data needs to be OB https://pydicom.github.io/pydicom/stable/_modules/pydicom/filewriter.html
                            ds[(0x7FE0,0x0010)].is_undefined_length = True 
                            ds.file_meta.TransferSyntaxUID = pydicom.uid.JPEG2000Lossless
                            ds.PixelRepresentation = 0
                            f.seek(0)    
                            ds.save_as(file, write_like_original=False)
                    else:
                        ds = pydicom.read_file(file)
                        ds.decompress()
                        ds.save_as(file, write_like_original=False)
                except:
                    print (traceback.format_exc())
                    passed = False
    except:
        passed = False
    failed = None
    if passed: 
        upload_dir = scanOutputDicomDir 
        
        
        
        try:
            
            
            #time.sleep(0.5)
            print ('Uploading files for scan %s' % scanid)
            queryArgs = {"format": "DICOM", "content": "DICOM"}
            if workflowId is not None:
                queryArgs["event_id"] = workflowId
            if uploadByRef:
                queryArgs["reference"] = os.path.abspath(upload_dir)
                r = sess.put(host + "/data/experiments/%s/scans/%s/resources/DICOM%s/files" % (session, scanid, '_COMPRESSED' if compress else ''), params=queryArgs)
                r.raise_for_status()
            else:
                queryArgs["extract"] = True
                queryArgs["overwrite"] = True
                (t, tempFilePath) = tempfile.mkstemp(suffix='.zip')
                zipdir(dirPath=os.path.abspath(upload_dir), zipFilePath=tempFilePath, includeDirInZip=False)
                files = {'file': open(tempFilePath, 'rb')}
                r = sess.post(host + "/data/experiments/%s/scans/%s/resources/DICOM%s/files" % (session, scanid, '_COMPRESSED' if compress else ''), params=queryArgs, files=files)
                r.raise_for_status()
                os.remove(tempFilePath)
            
            # delete AFTER upload so if the upload fails the delete doesn't go through. 
            try:
                queryArgs = {} 
                if workflowId is not None:
                    queryArgs["event_id"] = workflowId
                print ('Deleting previous DICOM files')
                r = sess.delete(host + "/data/experiments/%s/scans/%s/resources/DICOM%s" % (session, scanid, '_COMPRESSED' if not compress else ''), params=queryArgs)
                r.raise_for_status()
            except (requests.ConnectionError, requests.exceptions.RequestException) as e:
                print ("There was a problem deleting")
                print ("    " + str(e))
                print ("Skipping upload for scan %s." % scanid)
                
            break
        except:                
            failed = traceback.format_exc()
            
            #code.interact(local=locals())
                


    ##########
    # Clean up input directory
    print ('Cleaning up %s directory.' % scanDicomDir)
    for f in os.listdir(scanDicomDir):
        os.remove(os.path.join(scanDicomDir, f))
    os.rmdir(scanDicomDir)

    print ('All done with image conversion.')
    if failed is not None:
        raise Exception(failed)
