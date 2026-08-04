from fastapi.testclient import TestClient
from backend.main import app

def test_powerbi_endpoints():
    client = TestClient(app)
    
    # 1. Test status
    res_status = client.get("/api/v1/powerbi/status")
    print("Power BI Status Code:", res_status.status_code)
    assert res_status.status_code == 200, f"Expected 200, got {res_status.status_code}"
    print("Power BI Status Payload:", res_status.json())
    
    # 2. Test refresh
    res_refresh = client.post("/api/v1/powerbi/refresh")
    print("Power BI Refresh Code:", res_refresh.status_code)
    assert res_refresh.status_code == 200, f"Expected 200, got {res_refresh.status_code}"
    print("Power BI Refresh Payload:", res_refresh.json())
    
    # 3. Test schema
    res_schema = client.get("/api/v1/powerbi/schema")
    print("Power BI Schema Code:", res_schema.status_code)
    assert res_schema.status_code == 200, f"Expected 200, got {res_schema.status_code}"
    print("Power BI Schema Payload:", res_schema.json())
    
    print("\n=== Power BI API Verification PASSED Perfectly ===")

if __name__ == "__main__":
    test_powerbi_endpoints()
