{
  "assignment_name": "Todo API Assignment",
  "total_points": 100,
  "endpoints": [
    {
      "name": "Get All Todos",
      "path": "/api/todos",
      "method": "GET",
      "score": 20,
      "required_fields": ["id", "title", "completed"],
      "expected_status": 200,
      "test_cases": [
        {
          "description": "Should return array of todos",
          "validate": "is_array"
        }
      ]
    },
    {
      "name": "Create Todo",
      "path": "/api/todos",
      "method": "POST",
      "score": 25,
      "required_fields": ["id", "title", "completed"],
      "expected_status": 201,
      "request_body": {
        "title": "Test Todo",
        "completed": false
      },
      "test_cases": [
        {
          "description": "Should create and return new todo",
          "validate": "has_id"
        }
      ]
    },
    {
      "name": "Get Single Todo",
      "path": "/api/todos/1",
      "method": "GET",
      "score": 15,
      "required_fields": ["id", "title", "completed"],
      "expected_status": 200
    },
    {
      "name": "Update Todo",
      "path": "/api/todos/1",
      "method": "PUT",
      "score": 20,
      "required_fields": ["id", "title", "completed"],
      "expected_status": 200,
      "request_body": {
        "title": "Updated Todo",
        "completed": true
      }
    },
    {
      "name": "Delete Todo",
      "path": "/api/todos/1",
      "method": "DELETE",
      "score": 20,
      "expected_status": [200, 204]
    }
  ],
  "bonus_checks": [
    {
      "name": "Has OpenAPI Documentation",
      "check": "openapi_exists",
      "score": 10
    },
    {
      "name": "Proper Error Handling",
      "path": "/api/todos/99999",
      "method": "GET",
      "expected_status": 404,
      "score": 5
    }
  ]
}