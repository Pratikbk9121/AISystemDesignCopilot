"""
Helper script to add and validate new system design documents to the knowledge base

This script:
1. Validates document format and content
2. Checks for required sections
3. Provides a template for new documents
4. Helps maintain consistent quality across knowledge base
"""
import sys
from pathlib import Path
import argparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def create_template(output_path: Path, system_name: str):
    """
    Create a template for a new system design document
    
    Args:
        output_path: Where to save the template
        system_name: Name of the system (e.g., "Instagram", "LinkedIn")
    """
    template = f"""# {system_name} System Design

## Overview
Brief description of what {system_name} does and its primary purpose.

## Core Components

### 1. **Component Name**
- Description of the component
- Key responsibilities
- Technologies used

### 2. **Another Component**
- What it does
- How it scales
- Dependencies

(Add more components as needed)

## Database Architecture

### Primary Datastore
- **Database Type** (e.g., PostgreSQL, MongoDB):
  - What data is stored
  - Schema design considerations
  - Sharding strategy if applicable

### Caching Layer
- **Cache Type** (e.g., Redis, Memcached):
  - What is cached
  - Cache invalidation strategy
  - TTL policies

### (Add more data stores as needed)

## Scaling Strategy

### Horizontal Scaling
- How the system scales horizontally
- Sharding/partitioning strategies
- Load balancing approach

### Caching Strategy
- Multi-level caching
- Cache-aside vs write-through
- Invalidation policies

### Message Queue (if applicable)
- Queue technology (Kafka, RabbitMQ, SQS)
- Event-driven patterns
- Async processing

## API Design

### Example Endpoint 1
```
POST /api/v1/resource
Body: {{ "field": "value" }}
Response: {{ "id": "123", "status": "created" }}
```

### Example Endpoint 2
```
GET /api/v1/resource/{{id}}
Response: {{ "data": {{...}} }}
```

(Add more API examples)

## Trade-offs

### Trade-off 1: Option A vs Option B
- **Option A**: Pros and cons
- **Option B**: Pros and cons
- **Chosen Approach**: Which one and why

### Trade-off 2: Consistency vs Availability
- CAP theorem considerations
- Chosen consistency model
- Why this choice makes sense

(Add more trade-offs)

## Performance Optimizations

1. **Optimization 1**: Description and impact
2. **Optimization 2**: Description and impact
3. **Optimization 3**: Description and impact

## Capacity Estimates (Optional but Recommended)

- **Users**: Number of active users
- **Requests**: Requests per second (average and peak)
- **Storage**: Total storage requirements
- **Bandwidth**: Network bandwidth needs

## Key Insights

- Important lesson or pattern from this design
- Critical scalability consideration
- Unique challenge and how it's solved
- Real-world numbers if available
"""
    
    output_path.write_text(template)
    print(f"✅ Template created: {output_path}")
    print(f"\nNext steps:")
    print(f"1. Edit the template file: {output_path}")
    print(f"2. Fill in all sections with detailed information")
    print(f"3. Run validation: python scripts/add_knowledge_document.py --validate {output_path}")
    print(f"4. Re-index the knowledge base: python scripts/initialize_qdrant.py --clear")


def validate_document(doc_path: Path):
    """
    Validate a system design document for completeness
    
    Args:
        doc_path: Path to the document to validate
    
    Returns:
        Tuple of (is_valid, issues_list)
    """
    if not doc_path.exists():
        return False, [f"File not found: {doc_path}"]
    
    content = doc_path.read_text()
    issues = []
    
    # Check required sections
    required_sections = [
        "# ",  # Title
        "## Overview",
        "## Core Components",
        "## Database Architecture",
        "## Scaling Strategy",
        "## Trade-offs",
    ]
    
    for section in required_sections:
        if section not in content:
            issues.append(f"Missing required section: {section}")
    
    # Check for minimum content length
    if len(content) < 1000:
        issues.append(f"Document too short ({len(content)} chars). Aim for at least 1000 characters.")
    
    # Check for code blocks (API examples)
    if "```" not in content:
        issues.append("No code blocks found. Add API examples or data schemas.")
    
    # Check for bullet points
    if "- " not in content:
        issues.append("No bullet points found. Use lists for better readability.")
    
    # Warn about TODO or placeholder text
    placeholders = ["TODO", "TBD", "FIXME", "XXX"]
    for placeholder in placeholders:
        if placeholder in content:
            issues.append(f"Contains placeholder text: {placeholder}")
    
    is_valid = len(issues) == 0
    return is_valid, issues


def main():
    parser = argparse.ArgumentParser(
        description="Add and validate system design knowledge documents"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    # Create template command
    create_parser = subparsers.add_parser("create", help="Create a new document template")
    create_parser.add_argument("system_name", help="Name of the system (e.g., 'Instagram')")
    create_parser.add_argument(
        "--output",
        default="./data/system_design_docs",
        help="Output directory (default: ./data/system_design_docs)"
    )
    
    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate an existing document")
    validate_parser.add_argument("file_path", help="Path to the document to validate")
    
    args = parser.parse_args()
    
    if args.command == "create":
        system_name = args.system_name
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename
        filename = f"{system_name.lower().replace(' ', '_')}_system_design.md"
        output_path = output_dir / filename
        
        if output_path.exists():
            print(f"❌ File already exists: {output_path}")
            print(f"   Use --output to specify a different location or delete the existing file.")
            sys.exit(1)
        
        create_template(output_path, system_name)
    
    elif args.command == "validate":
        doc_path = Path(args.file_path)
        is_valid, issues = validate_document(doc_path)
        
        if is_valid:
            print(f"✅ Document is valid: {doc_path}")
            print(f"\nDocument stats:")
            content = doc_path.read_text()
            print(f"  - Size: {len(content)} characters")
            print(f"  - Lines: {len(content.splitlines())}")
            print(f"  - Sections: {content.count('## ')}")
            print(f"\nReady to add to knowledge base!")
            print(f"Run: python scripts/initialize_qdrant.py --clear")
        else:
            print(f"❌ Document has issues: {doc_path}\n")
            for issue in issues:
                print(f"  - {issue}")
            print(f"\nPlease fix these issues and validate again.")
            sys.exit(1)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
