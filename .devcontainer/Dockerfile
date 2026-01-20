FROM ubuntu:22.04

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=$USER_UID

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  wget \
  git \
  gnupg \
  unzip \
  build-essential \
  sudo \
  && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid $USER_GID $USERNAME \
  && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME -s /bin/bash \
  && echo $USERNAME ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/$USERNAME \
  && chmod 0440 /etc/sudoers.d/$USERNAME

# hadolint ignore=DL3008
RUN install -dm 755 /etc/apt/keyrings \
  && wget -qO - https://mise.jdx.dev/gpg-key.pub | gpg --dearmor | tee /etc/apt/keyrings/mise-archive-keyring.gpg > /dev/null \
  && echo "deb [signed-by=/etc/apt/keyrings/mise-archive-keyring.gpg arch=amd64] https://mise.jdx.dev/deb stable main" | tee /etc/apt/sources.list.d/mise.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends mise \
  && rm -rf /var/lib/apt/lists/*

USER $USERNAME
WORKDIR /home/$USERNAME

ENV PATH="/home/${USERNAME}/.local/share/mise/shims:${PATH}"

# Garante que o mise carregue sempre que abrir o terminal
RUN echo 'eval "$(mise activate bash)"' >> ~/.bashrc
