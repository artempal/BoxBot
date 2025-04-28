#!/usr/bin/env python
"""
Script to set up a local DynamoDB table for development.
This assumes you have Docker installed and running.
"""

import os
import sys
import logging
import subprocess
import time

# Add parent directory to path to import boxbot
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from boxbot.db.dynamodb import DynamoDBManager

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def start_dynamodb_local():
    """Start DynamoDB Local in a Docker container."""
    try:
        # Check if container is already running
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=dynamodb-local", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=True
        )
        
        if "dynamodb-local" in result.stdout:
            # Check if container is running
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=dynamodb-local", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True
            )
            
            if "dynamodb-local" in result.stdout:
                logger.info("DynamoDB Local is already running")
            else:
                # Start existing container
                logger.info("Starting existing DynamoDB Local container...")
                subprocess.run(
                    ["docker", "start", "dynamodb-local"],
                    check=True
                )
        else:
            # Create and start new container
            logger.info("Creating and starting DynamoDB Local container...")
            subprocess.run(
                [
                    "docker", "run", "-d",
                    "--name", "dynamodb-local",
                    "-p", "8000:8000",
                    "amazon/dynamodb-local:latest",
                    "-jar", "DynamoDBLocal.jar", "-sharedDb", "-inMemory"
                ],
                check=True
            )
            
        logger.info("DynamoDB Local is running on http://localhost:8000")
        
        # Wait for DynamoDB to be ready
        time.sleep(2)
        
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Error starting DynamoDB Local: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False

def setup_table():
    """Set up the DynamoDB table."""
    try:
        # Create table manager
        db_manager = DynamoDBManager()
        
        # Create the table
        db_manager.create_table_if_not_exists()
        
        logger.info(f"DynamoDB table '{db_manager.table_name}' is ready")
        return True
    except Exception as e:
        logger.error(f"Error creating DynamoDB table: {e}")
        return False

if __name__ == "__main__":
    if not start_dynamodb_local():
        sys.exit(1)
        
    if not setup_table():
        sys.exit(1)
        
    logger.info("Local development environment is ready")
    logger.info("Run 'python scripts/run_local.py' to start the bot") 