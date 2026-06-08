FROM mcr.microsoft.com/devcontainers/python:3

RUN apt-get update
RUN apt-get install -y vim tcpdump network-manager ca-certificates curl build-essential cmake libssl-dev

RUN apt-get install -y systemd
RUN ln -sf /lib/systemd/systemd /sbin/init

# Install Docker
RUN install -m 0755 -d /etc/apt/keyrings
RUN curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
RUN chmod a+r /etc/apt/keyrings/docker.asc
RUN echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    tee /etc/apt/sources.list.d/docker.list > /dev/null
RUN apt-get update
RUN apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
RUN usermod -aG docker vscode

ENTRYPOINT ["/sbin/init"]