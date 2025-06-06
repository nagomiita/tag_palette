# Dockerfile: OpenPose + Python API (Ubuntu + CUDA)
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu20.04

# Set non-interactive mode
ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y \
    build-essential cmake git wget curl unzip pkg-config \
    libopencv-dev python3-dev python3-pip python3-numpy \
    libopenblas-dev liblapack-dev libatlas-base-dev \
    libprotobuf-dev protobuf-compiler \
    libgoogle-glog-dev libgflags-dev \
    libboost-all-dev \
    libhdf5-dev \
    python3-opencv \
    && rm -rf /var/lib/apt/lists/*

# Clone OpenPose
WORKDIR /opt
RUN git clone https://github.com/CMU-Perceptual-Computing-Lab/openpose.git --depth 1

# Build OpenPose
WORKDIR /opt/openpose
RUN mkdir build && cd build && \
    cmake -DBUILD_PYTHON=ON \
          -DUSE_CUDNN=ON \
          -DUSE_CUDA=ON \
          -DBUILD_EXAMPLES=OFF \
          -DCMAKE_BUILD_TYPE=Release .. && \
    make -j"$(nproc)"

# Set environment for Python bindings
ENV PYTHONPATH=/opt/openpose/build/python
ENV LD_LIBRARY_PATH=/opt/openpose/build/lib:$LD_LIBRARY_PATH

# Copy Python wrapper shortcut
RUN ln -s /opt/openpose/build/python/openpose /usr/local/lib/python3.8/dist-packages/openpose

# Run test script
COPY test_pose.py /opt/openpose/test_pose.py
CMD ["python3", "/opt/openpose/test_pose.py"]
