"""
Example usage of the AI System Design Copilot API

This demonstrates:
1. Basic system design query
2. Conversational follow-up (refinement)
3. Handling the structured response
"""
import requests
import json
from typing import Dict, Any


BASE_URL = "http://localhost:8000"
API_PREFIX = "/api/v1/system-design"


def print_section(title: str):
    """Pretty print section headers"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_architecture(architecture: Dict[str, Any]):
    """Pretty print the architecture"""
    print("\n📦 SERVICES:")
    for service in architecture.get("services", []):
        print(f"   • {service}")
    
    print(f"\n💾 DATABASE:")
    print(f"   {architecture.get('database', 'N/A')}")
    
    print(f"\n📈 SCALING STRATEGY:")
    print(f"   {architecture.get('scaling_strategy', 'N/A')}")
    
    if architecture.get("tradeoffs"):
        print(f"\n⚖️  TRADE-OFFS:")
        for tradeoff in architecture["tradeoffs"]:
            print(f"   • {tradeoff['aspect']}: {tradeoff['recommendation']}")
    
    if architecture.get("non_functional_requirements"):
        print(f"\n🎯 NON-FUNCTIONAL REQUIREMENTS:")
        for key, value in architecture["non_functional_requirements"].items():
            print(f"   • {key}: {value}")


def print_evaluation(evaluation: Dict[str, Any]):
    """Pretty print the evaluation"""
    print(f"\n✅ CONFIDENCE SCORE: {evaluation['confidence_score']:.2f}")
    
    print(f"\n💪 STRENGTHS:")
    for strength in evaluation.get("strengths", []):
        print(f"   • {strength}")
    
    if evaluation.get("weaknesses"):
        print(f"\n⚠️  WEAKNESSES:")
        for weakness in evaluation["weaknesses"]:
            print(f"   • {weakness}")
    
    if evaluation.get("suggestions"):
        print(f"\n💡 SUGGESTIONS:")
        for suggestion in evaluation["suggestions"]:
            print(f"   • {suggestion}")


def example_1_basic_query():
    """Example 1: Basic system design query"""
    print_section("EXAMPLE 1: Basic System Design Query")
    
    url = f"{BASE_URL}{API_PREFIX}/query"
    
    payload = {
        "query": "Design a URL shortener like bit.ly that handles 1 billion URLs and 100 million daily redirects",
        "include_evaluation": True,
        "context": {
            "scale": "1B URLs, 100M daily redirects",
            "requirements": ["short URLs", "analytics", "custom URLs"],
            "region": "global"
        }
    }
    
    print(f"\n📤 REQUEST:")
    print(json.dumps(payload, indent=2))
    
    response = requests.post(url, json=payload)
    result = response.json()
    
    print(f"\n📥 RESPONSE:")
    print_architecture(result["architecture"])
    
    if result.get("evaluation"):
        print_evaluation(result["evaluation"])
    
    print(f"\n📊 TOKEN USAGE:")
    token_usage = result.get("token_usage", {})
    print(f"   Total Tokens: {token_usage.get('total_tokens', 0)}")
    print(f"   Estimated Cost: ${token_usage.get('estimated_cost_usd', 0):.4f}")
    
    # Return session ID for next example
    return result["session_id"]


def example_2_refinement(session_id: str):
    """Example 2: Refine the existing design"""
    print_section("EXAMPLE 2: Architecture Refinement (Follow-up)")
    
    url = f"{BASE_URL}{API_PREFIX}/query"
    
    payload = {
        "query": "How would you modify this design to handle 10x more traffic and add real-time analytics?",
        "session_id": session_id,  # Use same session for context
        "include_evaluation": True
    }
    
    print(f"\n📤 REFINEMENT REQUEST:")
    print(json.dumps(payload, indent=2))
    
    response = requests.post(url, json=payload)
    result = response.json()
    
    print(f"\n📥 REFINED DESIGN:")
    print_architecture(result["architecture"])
    
    if result.get("evaluation"):
        print_evaluation(result["evaluation"])


def example_3_conversation_history(session_id: str):
    """Example 3: Retrieve conversation history"""
    print_section("EXAMPLE 3: Retrieve Conversation History")
    
    url = f"{BASE_URL}{API_PREFIX}/conversation/{session_id}"
    
    response = requests.get(url)
    conversation = response.json()
    
    print(f"\n💬 CONVERSATION MESSAGES ({len(conversation['messages'])} total):")
    for i, msg in enumerate(conversation["messages"], 1):
        role = msg["role"].upper()
        content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
        print(f"\n   {i}. [{role}]")
        print(f"      {content}")


def example_4_health_check():
    """Example 4: Health check"""
    print_section("EXAMPLE 4: Health Check")
    
    url = f"{BASE_URL}{API_PREFIX}/health"
    
    response = requests.get(url)
    health = response.json()
    
    print(f"\n✅ API Status:")
    print(json.dumps(health, indent=2))


if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║       AI System Design Copilot - Example Usage               ║
    ║                                                              ║
    ║  Make sure the server is running:                           ║
    ║  $ uvicorn app.main:app --reload --port 8000                ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    try:
        # Example 1: Basic query
        session_id = example_1_basic_query()
        
        # Example 2: Refinement
        example_2_refinement(session_id)
        
        # Example 3: Conversation history
        example_3_conversation_history(session_id)
        
        # Example 4: Health check
        example_4_health_check()
        
        print("\n" + "=" * 80)
        print("  ✅ All examples completed successfully!")
        print("=" * 80 + "\n")
    
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to the server.")
        print("   Please ensure the server is running:")
        print("   $ uvicorn app.main:app --reload --port 8000\n")
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
