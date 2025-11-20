#!/bin/bash

set -e

echo "Generating gRPC code from proto files..."

python -m grpc_tools.protoc \
  -I./protos \
  --python_out=./services/document/app \
  --grpc_python_out=./services/document/app \
  ./protos/document_service.proto

sed -i '' 's/import document_service_pb2 as document__service__pb2/from . import document_service_pb2 as document__service__pb2/' ./services/document/app/*.py

echo "Generated for document-service"

python -m grpc_tools.protoc \
  -I./protos \
  --python_out=./services/signature/app \
  --grpc_python_out=./services/signature/app \
  ./protos/document_service.proto

sed -i '' 's/import document_service_pb2 as document__service__pb2/from . import document_service_pb2 as document__service__pb2/' ./services/signature/app/*.py

echo "Generated for signature-service"

echo "Proto generation complete"
