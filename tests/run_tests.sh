#!/bin/bash

# Test runner for TikTokSales integration tests
# Usage: ./run_tests.sh [test_pattern]
# Example: ./run_tests.sh test_full_pipeline
#          ./run_tests.sh TestChatEndpoint
#          ./run_tests.sh  (runs all tests)

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"

echo "================================"
echo "TikTokSales Integration Tests"
echo "================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Test directory: $SCRIPT_DIR"
echo ""

# Check if Docker containers are running
echo "Checking service health..."
echo ""

services=(
  "http://localhost:8081:chat-product"
  "http://localhost:8001:nlp-service"
  "http://localhost:8002:vision-service"
  "http://localhost:8082:ecommerce"
  "http://localhost:6379:redis"
)

all_healthy=true

for service in "${services[@]}"; do
  url="${service%%:*}"
  name="${service##*:}"
  
  if [[ "$name" == "redis" ]]; then
    if timeout 2 redis-cli -p 6379 ping > /dev/null 2>&1; then
      echo "✓ $name is running"
    else
      echo "✗ $name is NOT running (http://localhost:6379)"
      all_healthy=false
    fi
  else
    health_url="${url}/health"
    if timeout 2 curl -s "$health_url" > /dev/null 2>&1; then
      echo "✓ $name is running ($url)"
    else
      echo "✗ $name is NOT running ($url)"
      all_healthy=false
    fi
  fi
done

echo ""

if [ "$all_healthy" = false ]; then
  echo "⚠️  Some services are not running!"
  echo ""
  echo "Start them with:"
  echo "  cd $PROJECT_ROOT/infra"
  echo "  docker compose up -d"
  echo ""
  exit 1
fi

# Install test dependencies
echo "Installing test dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# Run tests
TEST_PATTERN="${1:-test_}"
echo ""
echo "Running tests matching: $TEST_PATTERN"
echo ""

cd "$PROJECT_ROOT"
python -m pytest \
  "$SCRIPT_DIR/test_full_pipeline.py::${TEST_PATTERN}" \
  "$SCRIPT_DIR/test_ecommerce.py::${TEST_PATTERN}" \
  "$SCRIPT_DIR/test_end_to_end.py::${TEST_PATTERN}" \
  -v \
  -s \
  --tb=short \
  --asyncio-mode=auto

echo ""
echo "✓ Tests completed!"
