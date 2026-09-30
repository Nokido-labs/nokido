# Use an official Python runtime as a parent image
# Make sure to use a version compatible with your project (check pyproject.toml)
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy the requirements file from the project root first to leverage Docker layer caching
# This assumes the Docker build context is the root of the Nokido project
COPY requirements.txt ./

# Install any needed packages specified in requirements.txt
# We add --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the agent's code into the container
# This assumes the mcp_agent_template is inside an 'app' directory
COPY app/agent_inspecteur_des_finances_publiques/ ./

# Expose the port the app runs on
EXPOSE 9039

# Define the entry point for the container.
# This will run the agent in server mode by default.
# Users can override this by passing 'stdio' as a command.
# e.g., docker run <imagename> stdio
ENTRYPOINT ["python", "main.py"]
CMD ["server"]
