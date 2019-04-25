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

LABEL org.nrg.commands="[{ \"name\": \"dcm2jp2k-session\", \"description\": \"Runs dcm2jp2k on a session's scans, and uploads the dcm jp2k\", \"version\": \"1.0\", \"schema-version\": \"1.0\", \"type\": \"docker\", \"image\": \"xnat/dcm2jp2k-session:1.0\", \"command-line\": \"python dcm2jp2k.py #SESSION_ID# #COMPRESS# --host \$XNAT_HOST --user \$XNAT_USER --pass \$XNAT_PASS --upload-by-ref False --dicomdir /dicom \", \"workdir\": \"/src\", \"override-entrypoint\": true, \"mounts\": [ { \"name\": \"dicom\", \"writable\": \"true\", \"path\": \"/dicom\" } ], \"inputs\": [ { \"name\": \"session_id\", \"description\": \"XNAT ID of the session\", \"type\": \"string\", \"required\": true, \"replacement-key\": \"#SESSION_ID#\", \"command-line-flag\": \"--session\" }, { \"name\": \"compress\", \"description\": \"Compress any existing DICOM scan resources? If False this will decompress\", \"type\": \"boolean\", \"required\": false, \"default-value\": true, \"replacement-key\": \"#COMPRESS#\", \"true-value\": \"True\", \"false-value\": \"False\", \"command-line-flag\": \"--compress\" } ], \"outputs\": [], \"xnat\": [ { \"name\": \"dcm2jp2k-session-session\", \"description\": \"Run dcm2jp2k-session on a Session\", \"contexts\": [\"xnat:imageSessionData\"], \"external-inputs\": [ { \"name\": \"session\", \"description\": \"Input session\", \"type\": \"Session\", \"required\": true } ], \"derived-inputs\": [ { \"name\": \"session-id\", \"description\": \"The session's id\", \"type\": \"string\", \"derived-from-wrapper-input\": \"session\", \"derived-from-xnat-object-property\": \"id\", \"provides-value-for-command-input\": \"session_id\" } ], \"output-handlers\": [] } ] }]" 
