from fastapi import FastAPI

app = FastAPI()

todos = [
    {"id": 1, "title": "Learn FastAPI", "completed": False}
]

@app.get("/api/todos")
def get_todos():
    return todos

@app.post("/api/todos")
def create_todo(todo: dict):
    new_todo = {
        "id": len(todos) + 1,
        "title": todo.get("title", ""),
        "completed": todo.get("completed", False)
    }
    todos.append(new_todo)
    return new_todo

@app.get("/api/todos/{todo_id}")
def get_todo(todo_id: int):
    for todo in todos:
        if todo["id"] == todo_id:
            return todo
    return {"error": "Not found"}

@app.delete("/api/todos/{todo_id}")
def delete_todo(todo_id: int):
    global todos
    todos = [t for t in todos if t["id"] != todo_id]
    return {"message": "Deleted"}
