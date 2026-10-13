FROM ghcr.io/luxonis/rae-base:2024.01.18-humble

ARG BUILD_TYPE="RelWithDebInfo"
ARG SIM=0
ENV DEBIAN_FRONTEND=noninteractive

# Replace the expired ROS repository key inherited from the base image.
RUN curl --fail --location \
        -o /tmp/ros2-apt-source.deb \
        "https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.jammy_all.deb" \
    && rm -f /etc/apt/sources.list.d/ros2-latest.list \
    && dpkg -i /tmp/ros2-apt-source.deb \
    && rm -f /tmp/ros2-apt-source.deb

# Upgrade inherited ROS dependencies for current RTAB-Map binaries and headers.
RUN apt-get update && apt-get -y install --no-install-recommends \
    software-properties-common \
    libusb-1.0-0-dev \
    python3-colcon-common-extensions \
    python3-rosdep \
    build-essential \
    busybox-static \
    gpiod \
    libasound2-dev \
    ros-humble-rmw-cyclonedds-cpp \
    gstreamer1.0-plugins-bad \
    alsa-utils \
    mpg123 \
    libmpg123-dev \
    ros-humble-diagnostic-updater \
    ros-humble-geometry-msgs \
    ros-humble-message-filters \
    ros-humble-pcl-ros \
    ros-humble-tf2 \
    ros-humble-tf2-ros \
    ros-humble-rtabmap-slam \
    unzip \
    ffmpeg \
    ros-humble-image-proc \
    git \
    htop \
    libsndfile1-dev \
    libsndfile1

RUN busybox --list | grep -qx devmem

RUN pip3 install openai ffmpeg-python

ENV WS=/ws
RUN mkdir -p $WS/src
COPY ./ .$WS/src/rae-ros

RUN rm -rf .$WS/src/rae-ros/assets
RUN rm -rf .$WS/src/rae-ros/rae_gazebo

RUN cd .$WS/ && apt update && rosdep install --from-paths src --ignore-src  -y --skip-keys depthai --skip-keys depthai_bridge --skip-keys depthai_ros_driver --skip-keys audio_msgs --skip-keys laserscan_kinect --skip-keys ira_laser_tools
RUN cd .$WS/ && . /opt/ros/${ROS_DISTRO}/setup.sh && . /sai_ros/spectacularai_ros2/install/setup.sh && . /${UNDERLAY_WS}/install/setup.sh && colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=${BUILD_TYPE}
RUN echo "if [ -f ${WS}/install/setup.bash ]; then source ${WS}/install/setup.bash; fi" >> $HOME/.bashrc
RUN echo "if [ -f ${WS}/install/setup.zsh ]; then source ${WS}/install/setup.zsh; fi" >> $HOME/.zshrc
RUN chmod +x /ws/src/rae-ros/entrypoint.sh

ENTRYPOINT [ "/ws/src/rae-ros/entrypoint.sh" ]

RUN rm -rf /usr/share/doc

CMD ["bash"]
