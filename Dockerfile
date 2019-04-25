FROM continuumio/miniconda3
MAINTAINER Jarrel Seah <jarrelscy@gmail.com>

WORKDIR /src
RUN conda install --quiet --yes \
    -c  conda-forge 'glymur=0.8.15'\
    'requests=2.21.0' \
    conda-build numpy mkl mkl-include cmake cffi typing setuptools && \
    rm -rf /var/lib/apt/lists/*    
 
RUN pip install git+https://github.com/jarrelscy/pydicom.git
COPY . /src

LABEL org.nrg.commands="[{\"mounts\": [{\"name\": \"dicom\", \"path\": \"/dicom\", \"writable\": \"true\"}], \"xnat\": [{\"name\": \"dcm2jp2k-session-session\", \"description\": \"Run dcm2jp2k-session on a Session\", \"contexts\": [\"xnat:imageSessionData\"], \"derived-inputs\": [{\"name\": \"session-id\", \"description\": \"The session's id\", \"derived-from-xnat-object-property\": \"id\", \"derived-from-wrapper-input\": \"session\", \"provides-value-for-command-input\": \"session_id\", \"type\": \"string\"}], \"external-inputs\": [{\"name\": \"session\", \"description\": \"Input session\", \"type\": \"Session\", \"required\": true}], \"output-handlers\": []}], \"workdir\": \"/src\", \"inputs\": [{\"name\": \"session_id\", \"description\": \"XNAT ID of the session\", \"replacement-key\": \"#SESSION_ID#\", \"required\": true, \"type\": \"string\", \"command-line-flag\": \"--session\"}, {\"false-value\": \"False\", \"name\": \"compress\", \"description\": \"Compress any existing DICOM scan resources? If False this will decompress\", \"required\": false, \"replacement-key\": \"#COMPRESS#\", \"default-value\": true, \"type\": \"boolean\", \"true-value\": \"True\", \"command-line-flag\": \"--compress\"}], \"type\": \"docker\", \"version\": \"1.0\", \"image\": \"xnat/dcm2jp2k-session:1.0\", \"command-line\": \"python dcm2jp2k.py #SESSION_ID# #COMPRESS# --host \$XNAT_HOST --user \$XNAT_USER --pass \$XNAT_PASS --upload-by-ref False --dicomdir /dicom \", \"name\": \"dcm2jp2k-session\", \"description\": \"Runs dcm2jp2k on a session's scans, and uploads the dcm jp2k\", \"schema-version\": \"1.0\", \"outputs\": [], \"override-entrypoint\": true}]"
 
