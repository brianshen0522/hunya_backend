# Use an official Python runtime as a base image
FROM python:3.9

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        libreoffice \
        libreoffice-java-common \
        default-jre \
        fontconfig && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Copy Windows fonts to the system fonts directory
COPY ./fonts/win /usr/share/fonts/

# Refresh the font cache
RUN fc-cache -f -v

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Command to run the application
CMD ["python", "main.py"]
