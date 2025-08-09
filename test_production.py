#!/usr/bin/env python3
"""
Test script for production endpoints
Replace the URLs with your actual deployed URLs
"""

import requests
import json

def test_production_endpoints():
    """Test production endpoints"""
    
    # Replace these with your actual URLs
    backend_url = "https://cratebuddy.onrender.com"      # Your Render backend
    frontend_url = "https://cratebuddy.vercel.app"       # Your Vercel frontend
    
    print("🚀 Testing Production Endpoints")
    print("=" * 50)
    
    # Test backend health
    try:
        print(f"\n🔍 Testing Backend Health: {backend_url}/healthz")
        r = requests.get(f"{backend_url}/healthz", timeout=10)
        print(f"✅ Status: {r.status_code}")
        print(f"✅ Response: {r.text}")
    except Exception as e:
        print(f"❌ Backend Health Failed: {e}")
    
    # Test backend scraping
    try:
        print(f"\n🔍 Testing Backend Scraping: {backend_url}/test-scraping")
        r = requests.get(f"{backend_url}/test-scraping", timeout=15)
        print(f"✅ Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"✅ Scraping Test: {data.get('status', 'unknown')}")
        else:
            print(f"❌ Response: {r.text}")
    except Exception as e:
        print(f"❌ Backend Scraping Failed: {e}")
    
    # Test frontend accessibility
    try:
        print(f"\n🔍 Testing Frontend: {frontend_url}")
        r = requests.get(frontend_url, timeout=10)
        print(f"✅ Status: {r.status_code}")
        print(f"✅ Frontend accessible")
    except Exception as e:
        print(f"❌ Frontend Failed: {e}")
    
    print("\n" + "=" * 50)
    print("📝 Next Steps:")
    print("1. Update VITE_API_URL in Vercel environment variables")
    print("2. Redeploy frontend")
    print("3. Test search functionality")

if __name__ == "__main__":
    test_production_endpoints()
