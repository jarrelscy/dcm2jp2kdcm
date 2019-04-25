FROM continuumio/miniconda3
MAINTAINER Jarrel Seah <jarrelscy@gmail.com>
COPY . /src
WORKDIR /src
RUN conda install --quiet --yes \
    'glymur=0.8.15' \
    'requests=2.21.0' \
    conda-build numpy pyyaml scipy ipython mkl mkl-include cmake cffi typing setuptools && \
    rm -rf /var/lib/apt/lists/*    
RUN pip install -r requirements.txt
