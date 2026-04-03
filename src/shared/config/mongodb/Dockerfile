# Use an official Python runtime as a parent image
FROM python:3.10

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file and install Python dependencies
COPY src/shared/config/mongodb/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python scripts
COPY src/shared/config/mongodb/setup_mongodb.py /app
COPY src/shared/config/mongodb/seed_database.py /app
COPY src/shared/config/mongodb/entrypoint.sh /app

# Normalize line endings and make the entrypoint script executable
RUN sed -i 's/\r$//' entrypoint.sh && chmod +x entrypoint.sh

# Set the entrypoint to the shell script
ENTRYPOINT ["/app/entrypoint.sh"]
