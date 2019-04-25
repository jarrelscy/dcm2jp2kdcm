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
from shutil import copy as fileCopy
from collections import OrderedDict
import requests.packages.urllib3
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

BIDSVERSION = "1.0.1"

parser = argparse.ArgumentParser(description="Run dcm2niix on every file in a session")
parser.add_argument("--host", default="https://cnda.wustl.edu", help="CNDA host", required=True)
parser.add_argument("--user", help="CNDA username", required=True)
parser.add_argument("--password", help="Password", required=True)
parser.add_argument("--session", help="Session ID", required=True)
parser.add_argument("--subject", help="Subject Label", required=False)
parser.add_argument("--project", help="Project", required=False)
parser.add_argument("--dicomdir", help="Root output directory for DICOM files", required=True)
parser.add_argument("--overwrite", help="Overwrite NIFTI files if they exist")
parser.add_argument("--upload-by-ref", help="Upload \"by reference\". Only use if your host can read your file system.")
parser.add_argument("--workflowId", help="Pipeline workflow ID")
parser.add_argument('--version', action='version', version='%(prog)s 1')

args, unknown_args = parser.parse_known_args()
host = cleanServer(args.host)
session = args.session
subject = args.subject
project = args.project
overwrite = isTrue(args.overwrite)
dicomdir = args.dicomdir
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

    # BIDS subject name
    base = "sub-" + subject + "_"

    # Get scan resources
    print "Get scan resources for scan %s." % scanid
    r = get(host + "/data/experiments/%s/scans/%s/resources" % (session, scanid), params={"format": "json"})
    scanResources = r.json()["ResultSet"]["Result"]
    print 'Found resources %s.' % ', '.join(res["label"] for res in scanResources)


    ##########
    # Prepare DICOM directory structure
    print
    scanDicomDir = os.path.join(dicomdir, scanid)
    if not os.path.isdir(scanDicomDir):
        print 'Making scan DICOM directory %s.' % scanDicomDir
        os.mkdir(scanDicomDir)
    # Remove any existing files in the builddir.
    # This is unlikely to happen in any environment other than testing.
    for f in os.listdir(scanDicomDir):
        os.remove(os.path.join(scanDicomDir, f))

    ##########
    # Get list of DICOMs/IMAs

    # set resourceid. This will only be set if hasIma is true and we've found a resource id
    resourceid = None

    if not usingDicom:

        print 'Get IMA resource id for scan %s.' % scanid
        r = get(host + "/data/experiments/%s/scans/%s/resources" % (session, scanid), params={"format": "json"})
        resourceDict = {resource['format']: resource['xnat_abstractresource_id'] for resource in r.json()["ResultSet"]["Result"]}

        if resourceDict["IMA"]:
            resourceid = resourceDict["IMA"]
        else:
            print "Couldn't get xnat_abstractresource_id for IMA file list."

    # Deal with DICOMs
    print 'Get list of DICOM files for scan %s.' % scanid

    if usingDicom:
        filesURL = host + "/data/experiments/%s/scans/%s/resources/DICOM/files" % (session, scanid)
    elif resourceid is not None:
        filesURL = host + "/data/experiments/%s/scans/%s/resources/%s/files" % (session, scanid, resourceid)
    else:
        print "Trying to convert IMA files but there is no resource id available. Skipping."
        continue

    r = get(filesURL, params={"format": "json"})
    # I don't like the results being in a list, so I will build a dict keyed off file name
    dicomFileDict = {dicom['Name']: {'URI': host + dicom['URI']} for dicom in r.json()["ResultSet"]["Result"]}

    # Have to manually add absolutePath with a separate request
    r = get(filesURL, params={"format": "json", "locator": "absolutePath"})
    for dicom in r.json()["ResultSet"]["Result"]:
        dicomFileDict[dicom['Name']]['absolutePath'] = dicom['absolutePath']

    ##########
    # Download DICOMs
    print "Downloading files for scan %s." % scanid
    os.chdir(scanDicomDir)

    # Check secondary
    # Download any one DICOM from the series and check its headers
    # If the headers indicate it is a secondary capture, we will skip this series.
    dicomFileList = dicomFileDict.items()

    (name, pathDict) = dicomFileList[0]
    download(name, pathDict)

    if usingDicom:
        print 'Checking modality in DICOM headers of file %s.' % name
        d = dicomLib.read_file(name)
        modalityHeader = d.get((0x0008, 0x0060), None)
        if modalityHeader:
            print 'Modality header: %s' % modalityHeader
            modality = modalityHeader.value.strip("'").strip('"')
            if modality == 'SC' or modality == 'SR':
                print 'Scan %s is a secondary capture. Skipping.' % scanid
                continue
        else:
            print 'Could not read modality from DICOM headers. Skipping.'
            continue

    ##########
    # Download remaining DICOMs
    for name, pathDict in dicomFileList[1:]:
        download(name, pathDict)

    os.chdir(builddir)
    print 'Done downloading for scan %s.' % scanid
    print

    

    ##########
    # Upload results
    print
    print 'Preparing to upload files for scan %s.' % scanid

    # If we have a NIFTI resource and we've reached this point, we know overwrite=True.
    # We should delete the existing NIFTI resource.
    if hasNifti:
        print "Scan %s has a preexisting NIFTI resource. Deleting it now." % scanid

        try:
            queryArgs = {}
            if workflowId is not None:
                queryArgs["event_id"] = workflowId
            r = sess.delete(host + "/data/experiments/%s/scans/%s/resources/NIFTI" % (session, scanid), params=queryArgs)
            r.raise_for_status()

            r = sess.delete(host + "/data/experiments/%s/scans/%s/resources/BIDS" % (session, scanid), params=queryArgs)
            r.raise_for_status()
        except (requests.ConnectionError, requests.exceptions.RequestException) as e:
            print "There was a problem deleting"
            print "    " + str(e)
            print "Skipping upload for scan %s." % scanid
            continue

    # Uploading
    print 'Uploading files for scan %s' % scanid
    queryArgs = {"format": "DICOM", "content": "DICOM_COMPRESSED"}
    if workflowId is not None:
        queryArgs["event_id"] = workflowId
    if uploadByRef:
        queryArgs["reference"] = os.path.abspath(scanImgDir)
        r = sess.put(host + "/data/experiments/%s/scans/%s/resources/NIFTI/files" % (session, scanid), params=queryArgs)
    else:
        queryArgs["extract"] = True
        (t, tempFilePath) = tempfile.mkstemp(suffix='.zip')
        zipdir(dirPath=os.path.abspath(scanImgDir), zipFilePath=tempFilePath, includeDirInZip=False)
        files = {'file': open(tempFilePath, 'rb')}
        r = sess.put(host + "/data/experiments/%s/scans/%s/resources/NIFTI/files" % (session, scanid), params=queryArgs, files=files)
        os.remove(tempFilePath)
    r.raise_for_status()


    ##########
    # Clean up input directory
    print 'Cleaning up %s directory.' % scanDicomDir
    for f in os.listdir(scanDicomDir):
        os.remove(os.path.join(scanDicomDir, f))
    os.rmdir(scanDicomDir)

    print 'All done with image conversion.'

##########
# Generate session-level metadata files
previouschanges = ""

# Remove existing files if they are there
print "Check for presence of session-level BIDS data"
r = get(host + "/data/experiments/%s/resources" % session, params={"format": "json"})
sessionResources = r.json()["ResultSet"]["Result"]
print 'Found resources %s.' % ', '.join(res["label"] for res in sessionResources)

# Do initial checks to determine if session-level BIDS metadata is present
hasSessionBIDS = any([res["label"] == "BIDS" for res in sessionResources])

if hasSessionBIDS:
    print "Session has preexisting BIDS resource. Deleting previous BIDS metadata if present."

    # Consider making CHANGES a real, living changelog
    # r = get( host + "/data/experiments/%s/resources/BIDS/files/CHANGES"%(session) )
    # previouschanges = r.text
    # print previouschanges

    try:
        queryArgs = {}
        if workflowId is not None:
            queryArgs["event_id"] = workflowId

        r = sess.delete(host + "/data/experiments/%s/resources/BIDS" % session, params=queryArgs)
        r.raise_for_status()
        uploadSessionBids = True
    except (requests.ConnectionError, requests.exceptions.RequestException) as e:
        print "There was a problem deleting"
        print "    " + str(e)
        print "Skipping upload for session-level files."
        uploadSessionBids = False

    print "Done"
    print ""

# Fetch metadata from project
print "Fetching project {} metadata".format(project)
rawprojectdata = get(host + "/data/projects/%s" % project, params={"format": "json"})
projectdata = rawprojectdata.json()
print "Got project metadata\n"

# Build dataset description
print "Constructing BIDS data"
dataset_description = OrderedDict()
dataset_description['Name'] = project

dataset_description['BIDSVersion'] = BIDSVERSION

# License- to be added later on after discussion of sensible default options
# dataset_description['License'] = None

# Compile investigators and PI into names list
invnames = []
invfield = [x for x in projectdata["items"][0]["children"] if x["field"] == "investigators/investigator"]
print str(invfield)

if invfield != []:
    invs = invfield[0]["items"]

    for i in invs:
        invnames.append(" ".join([i["data_fields"]["firstname"], i["data_fields"]["lastname"]]))

pifield = [x for x in projectdata["items"][0]["children"] if x["field"] == "PI"]

if pifield != []:
    pi = pifield[0]["items"][0]["data_fields"]
    piname = " ".join([pi["firstname"], pi["lastname"]])

    if piname in invnames:
        invnames.remove(piname)

    invnames.insert(0, piname + " (PI)")

if invnames != []:
    dataset_description['Authors'] = invnames

# Other metadata - to be added later on
# dataset_description['Acknowledgments'] = None
# dataset_description['HowToAcknowledge'] = None
# dataset_description['Funding'] = None
# dataset_description['ReferencesAndLinks'] = None

# Session identifier
dataset_description['DatasetDOI'] = host + '/data/experiments/' + session

# Upload
queryArgs = {"format": "BIDS", "content": "BIDS", "tags": "BIDS", "inbody": "true"}
if workflowId is not None:
    queryArgs["event_id"] = workflowId

r = sess.put(host + "/data/experiments/%s/resources/BIDS/files/dataset_description.json" % session, json=dataset_description, params=queryArgs)
r.raise_for_status()

# Generate CHANGES
changes = "1.0 " + time.strftime("%Y-%m-%d") + "\n\n - Initial release."

# Upload
h = {"content-type": "text/plain"}
r = sess.put(host + "/data/experiments/%s/resources/BIDS/files/CHANGES" % session, data=changes, params=queryArgs, headers=h)
r.raise_for_status()

# All done
print 'All done with session-level metadata.'
