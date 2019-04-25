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
