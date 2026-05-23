#!/bin/bash

echo "🧪 Comprehensive Knowledge Handling Tests"
echo "=========================================="
echo ""

test_query() {
    local name="$1"
    local query="$2"
    local expected="$3"
    
    echo "📝 Test: $name"
    echo "   Query: \"$query\""
    
    result=$(curl -s -X POST http://localhost:8000/api/v1/system-design/query \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"$query\", \"include_evaluation\": false}")
    
    confidence=$(echo "$result" | jq -r '.confidence_metrics.overall_confidence')
    insufficient=$(echo "$result" | jq -r '.insufficient_knowledge')
    has_warning=$(echo "$result" | jq -r '.confidence_warning != null')
    
    echo "   Confidence: $confidence"
    echo "   Insufficient: $insufficient"
    echo "   Has Warning: $has_warning"
    
    if [ "$expected" = "HIGH" ]; then
        if [ "$insufficient" = "false" ] && [ "$has_warning" = "false" ] && (( $(echo "$confidence >= 0.6" | bc -l) )); then
            echo "   ✅ PASS - High confidence, no warnings"
        else
            echo "   ❌ FAIL - Expected high confidence without warnings"
        fi
    elif [ "$expected" = "MEDIUM" ]; then
        if [ "$insufficient" = "false" ] && [ "$has_warning" = "true" ]; then
            echo "   ✅ PASS - Generated with warning"
        else
            echo "   ❌ FAIL - Expected warning"
        fi
    elif [ "$expected" = "LOW" ]; then
        if [ "$insufficient" = "true" ]; then
            echo "   ✅ PASS - Refused due to insufficient knowledge"
        else
            echo "   ❌ FAIL - Expected refusal"
        fi
    fi
    echo ""
}

echo "🔵 HIGH CONFIDENCE TESTS (Should generate without warnings)"
echo "============================================================"
test_query "Twitter" "Design Twitter" "HIGH"
test_query "WhatsApp" "Design WhatsApp messaging platform" "HIGH"
test_query "URL Shortener" "Design a URL shortener like bit.ly" "HIGH"

echo ""
echo "🟡 MEDIUM CONFIDENCE TESTS (Should generate WITH warnings)"
echo "==========================================================="
test_query "Medical Imaging" "Design a real-time medical imaging analysis system" "MEDIUM"
test_query "Pinterest" "Design Pinterest image sharing platform" "MEDIUM"

echo ""
echo "🔴 LOW CONFIDENCE TESTS (Should REFUSE)"
echo "========================================"
test_query "Nonsense Query" "xylophone purple elephant dancing moonbeam" "LOW"
test_query "Satellite Network" "Design a low-earth orbit satellite communication network" "LOW"
test_query "Nuclear Reactor" "Design a nuclear reactor control system" "LOW"
test_query "Cryptocurrency Mining" "Design a proof-of-work cryptocurrency mining pool" "LOW"

echo ""
echo "✅ All tests complete!"
echo ""
echo "📊 Summary:"
echo "   - High confidence tests expect: confidence >= 0.6, no warnings"
echo "   - Medium confidence tests expect: warnings present"
echo "   - Low confidence tests expect: insufficient_knowledge = true"
