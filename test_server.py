#!/usr/bin/env python3
"""
Simple test to verify the FastAPI server can start and respond to basic requests.
"""

import asyncio
import httpx
from utils import app

async def test_server():
    """Test the FastAPI server endpoints."""
    
    # Test the documentation endpoint
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        print("Testing FastAPI Python Code Executor")
        print("=" * 50)
        
        # Test 1: Get allowed libraries documentation
        print("\n📚 Test 1: Getting allowed libraries documentation...")
        try:
            response = await client.get("/docs/allowed-libraries-versions")
            if response.status_code == 200:
                print("✅ Documentation endpoint working")
                print("Response preview:", response.text[:200] + "...")
            else:
                print(f"❌ Documentation endpoint failed: {response.status_code}")
        except Exception as e:
            print(f"❌ Documentation endpoint error: {e}")
        
        # Test 2: Execute simple valid code
        print("\n🐍 Test 2: Executing simple valid Python code...")
        try:
            test_code = """
import json
import pandas as pd

print("Hello from FastAPI Python executor!")
data = {"message": "test", "numbers": [1, 2, 3]}
print(f"Test data: {data}")

# Create a simple file
with open("test_output.txt", "w") as f:
    f.write("Test execution successful!")
"""
            response = await client.post("/execute_python_code", 
                                       json={"code": test_code})
            if response.status_code == 200:
                result = response.json()
                print("✅ Code execution successful")
                print("Output:", result.get("output", "")[:200] + "...")
                print("Artifacts:", result.get("artifacts", []))
            else:
                print(f"❌ Code execution failed: {response.status_code}")
                print("Response:", response.text)
        except Exception as e:
            print(f"❌ Code execution error: {e}")
        
        # Test 3: Try invalid code (should be rejected)
        print("\n🚫 Test 3: Testing validation with invalid code...")
        try:
            invalid_code = """
import numpy as np  # Not allowed
import requests     # Not allowed
print("This should be rejected")
"""
            response = await client.post("/execute_python_code", 
                                       json={"code": invalid_code})
            if response.status_code == 400:
                print("✅ Invalid code properly rejected")
                print("Error message:", response.json().get("detail", ""))
            else:
                print(f"❌ Invalid code not rejected properly: {response.status_code}")
        except Exception as e:
            print(f"❌ Invalid code test error: {e}")
    
    print("\n✅ All tests completed!")

if __name__ == "__main__":
    print("FastAPI Python Code Executor - Test Script")
    print("This script tests the FastAPI server functionality")
    print()
    
    # Run the async test
    asyncio.run(test_server())
