#!/bin/bash
echo "Submitting request..."
response=$(curl -s -X POST http://localhost:8000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Hello! How are you today? Please reply with a short JSON.",
    "is_image": false,
    "force_json": true
}')

echo "Response from submit:"
echo $response

task_id=$(echo $response | jq -r '.task_id')

if [ "$task_id" == "null" ]; then
    echo "Failed to get task_id"
    exit 1
fi

echo "Streaming task $task_id..."
curl -N http://localhost:8000/api/v1/stream/$task_id
