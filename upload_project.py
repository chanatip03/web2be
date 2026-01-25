#!/usr/bin/env python3
import requests
import os
import sys
from pathlib import Path

def upload_project(project_path, server_url="http://localhost:9000"):
    """Upload project folder to grader"""
    
    if not os.path.exists(project_path):
        print(f"Error: Path not found: {project_path}")
        return
    
    print(f"Uploading project from: {project_path}")
    
    files_to_upload = []
    file_count = 0
    
    # Collect all files
    for root, dirs, files in os.walk(project_path):
        # Skip hidden folders and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
        
        for file in files:
            if file.startswith('.'):
                continue
                
            file_path = os.path.join(root, file)
            rel_path = os.path.relpath(file_path, project_path)
            
            try:
                files_to_upload.append(
                    ('files', (rel_path, open(file_path, 'rb')))
                )
                file_count += 1
            except Exception as e:
                print(f"Warning: Could not read {rel_path}: {e}")
    
    print(f"Uploading {file_count} files...")
    
    try:
        response = requests.post(
            f"{server_url}/inspect",
            files=files_to_upload,
            params={"grading_mode": "simple"}
        )
        
        result = response.json()
        
        # Display results
        print("\n" + "="*50)
        print("GRADING RESULTS")
        print("="*50)
        print(f"Framework: {result['project_info']['framework']}")
        print(f"Score: {result['grading_result']['total']}/{result['grading_result']['max_score']}")
        print(f"Grade: {result['grading_result']['grade']}")
        
        if result['grading_result'].get('all_endpoints_passed'):
            print("✅ All endpoints PASSED!")
        else:
            print("❌ Some endpoints FAILED")
        
        print("\nDetails:")
        for detail in result['grading_result']['details']:
            status = "✅" if detail['status'] == "PASS" else "❌"
            print(f"  {status} {detail['name']}: {detail['message']}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Close all file handles
        for _, (_, file_obj) in files_to_upload:
            file_obj.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_project.py <project_path>")
        sys.exit(1)
    
    upload_project(sys.argv[1])