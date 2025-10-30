"""
Test script for API endpoints and Temporal workflows.

This script tests the new questionnaire analysis endpoints.

PREREQUISITES:
1. Temporal server must be running: temporal server start-dev
2. Worker must be running: python backend/worker.py
3. API server must be running: python backend/app.py
"""

import requests
import time
import json

API_BASE_URL = "http://localhost:8000"


def test_health_check():
    """Test that API server is running."""
    print("\n" + "=" * 80)
    print("TEST 1: Health Check")
    print("=" * 80)

    try:
        response = requests.get(f"{API_BASE_URL}/health")
        if response.status_code == 200:
            print("[OK] API server is running")
            print(f"Response: {response.json()}")
            return True
        else:
            print(f"[FAIL] Health check failed: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("[FAIL] Cannot connect to API server at", API_BASE_URL)
        print("\nPlease start the API server:")
        print("  cd backend")
        print("  python app.py")
        return False


def test_start_analysis():
    """Test starting questionnaire analysis workflow."""
    print("\n" + "=" * 80)
    print("TEST 2: Start Questionnaire Analysis")
    print("=" * 80)

    # Prepare test data
    request_data = {
        "session_id": "test-session-123",
        "company_data": {
            "company_name": "Microsoft",
            "sector": "Technology",
            "cloud_provider": "AWS"
        },
        "configuration": {
            "environment": "multi-account",
            "regions": ["us-east-1", "us-west-2"]
        }
    }

    print("\nStarting analysis workflow...")
    print(f"Session ID: {request_data['session_id']}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/questionnaire/analyze",
            json=request_data,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            print("[OK] Workflow started successfully")
            print(f"Workflow ID: {result['workflow_id']}")
            print(f"Status: {result['status']}")
            print(f"Sections to process: {result['sections_count']}")
            return result['workflow_id']
        else:
            print(f"[FAIL] Failed to start workflow: {response.status_code}")
            print(f"Error: {response.text}")
            return None

    except requests.exceptions.ConnectionError:
        print("[FAIL] Cannot connect to API server")
        return None
    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        return None


def test_get_progress(workflow_id, max_iterations=30):
    """Test getting workflow progress."""
    print("\n" + "=" * 80)
    print("TEST 3: Monitor Workflow Progress")
    print("=" * 80)

    print(f"\nMonitoring workflow: {workflow_id}")
    print("Polling every 2 seconds...\n")

    for i in range(max_iterations):
        try:
            response = requests.get(
                f"{API_BASE_URL}/api/questionnaire/progress/{workflow_id}",
                timeout=10
            )

            if response.status_code == 200:
                result = response.json()
                status = result['status']
                progress = result.get('progress', {})

                sections_completed = progress.get('sections_completed', 0)
                total_sections = progress.get('total_sections', 0)
                predictions_made = progress.get('predictions_made', 0)
                current_section = progress.get('current_section', '')

                # Display progress
                if total_sections > 0:
                    percentage = int((sections_completed / total_sections) * 100)
                    bar_length = 40
                    filled = int((percentage / 100) * bar_length)
                    bar = '=' * filled + '-' * (bar_length - filled)

                    print(f"\r[{bar}] {percentage}% | "
                          f"Section {sections_completed}/{total_sections} | "
                          f"Predictions: {predictions_made} | "
                          f"Status: {status}", end='', flush=True)

                # Check if completed
                if status == 'completed':
                    print("\n\n[OK] Workflow completed successfully!")
                    print(f"Total predictions: {predictions_made}")
                    print(f"Sections processed: {sections_completed}/{total_sections}")
                    return True
                elif status == 'failed':
                    print("\n\n[FAIL] Workflow failed")
                    return False

                # Wait before next poll
                time.sleep(2)
            else:
                print(f"\n[WARN] Progress check returned {response.status_code}")
                time.sleep(2)

        except Exception as e:
            print(f"\n[ERROR] {str(e)}")
            time.sleep(2)

    print("\n\n[TIMEOUT] Workflow did not complete within expected time")
    return False


def test_cancel_workflow(workflow_id):
    """Test cancelling a workflow."""
    print("\n" + "=" * 80)
    print("TEST 4: Cancel Workflow")
    print("=" * 80)

    print(f"\nCancelling workflow: {workflow_id}")

    try:
        response = requests.post(
            f"{API_BASE_URL}/api/questionnaire/cancel/{workflow_id}",
            timeout=10
        )

        if response.status_code == 200:
            result = response.json()
            print("[OK] Workflow cancelled successfully")
            print(f"Status: {result['status']}")
            return True
        else:
            print(f"[FAIL] Failed to cancel: {response.status_code}")
            return False

    except Exception as e:
        print(f"[FAIL] Error: {str(e)}")
        return False


def main():
    """Run all API tests."""
    print("\n" + "=" * 80)
    print("QUESTIONNAIRE ANALYSIS API - TEST SUITE")
    print("=" * 80)

    print("\nIMPORTANT: Before running these tests, make sure:")
    print("1. Temporal server is running: temporal server start-dev")
    print("2. Worker is running: python backend/worker.py")
    print("3. API server is running: python backend/app.py")
    print("\nStarting tests...")
    # try:
    #     input()
    # except KeyboardInterrupt:
    #     print("\n\nTests cancelled by user")
    #     return

    # Test 1: Health check
    if not test_health_check():
        print("\n[ABORT] Cannot proceed without running API server")
        return

    # Test 2: Start analysis
    workflow_id = test_start_analysis()
    if not workflow_id:
        print("\n[ABORT] Cannot proceed without starting workflow")
        print("\nPossible issues:")
        print("1. Temporal server not running")
        print("2. Worker not running")
        print("3. Firestore not configured")
        return

    # Test 3: Monitor progress
    success = test_get_progress(workflow_id)

    if success:
        print("\n" + "=" * 80)
        print("ALL API TESTS PASSED [OK]")
        print("=" * 80)
        print("\nThe questionnaire analysis workflow is working correctly!")
        print("\nYou can now:")
        print("1. Test with the frontend UI")
        print("2. Check Temporal UI at: http://localhost:8233")
        print("3. View workflow execution details")
    else:
        print("\n" + "=" * 80)
        print("TESTS INCOMPLETE")
        print("=" * 80)
        print("\nThe workflow may still be running or encountered issues.")
        print("Check Temporal UI at: http://localhost:8233")

    # Optional: Test cancellation with a new workflow
    print("\n\nWould you like to test workflow cancellation? (y/n): ", end='')
    try:
        choice = input().strip().lower()
        if choice == 'y':
            # Start a new workflow for cancellation test
            cancel_workflow_id = test_start_analysis()
            if cancel_workflow_id:
                time.sleep(3)  # Let it run for a bit
                test_cancel_workflow(cancel_workflow_id)
    except KeyboardInterrupt:
        print("\nSkipping cancellation test")


if __name__ == "__main__":
    main()
