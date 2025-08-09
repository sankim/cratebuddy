#!/usr/bin/env python3
"""
Test script to verify Bandcamp scraping functionality

Note: Make sure to activate the virtual environment first:
source server/venv/bin/activate
"""
import requests
import json

def test_api_endpoint():
    """Test the main API endpoint"""
    base_url = "http://localhost:5002"  # Change this to your server URL
    
    print("Testing API endpoints...")
    
    # Test health endpoint
    try:
        response = requests.get(f"{base_url}/healthz")
        print(f"Health check: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"Health check failed: {e}")
    
    # Test scraping endpoint
    try:
        response = requests.get(f"{base_url}/test-scraping")
        print(f"Scraping test: {response.status_code} - {response.json()}")
    except Exception as e:
        print(f"Scraping test failed: {e}")
    
    # Test recommendation endpoint with a simple username
    try:
        test_data = {"input": "bandcamp"}  # Use a simple, public username
        response = requests.post(f"{base_url}/recommend", json=test_data)
        print(f"Recommendation test: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Got {len(data.get('recommendations', []))} recommendations")
        else:
            print(f"Error: {response.json()}")
    except Exception as e:
        print(f"Recommendation test failed: {e}")

if __name__ == "__main__":
    test_api_endpoint()
