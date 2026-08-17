import os
import google.generativeai as genai


# ============================================================
# 1. Get API key
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

print("=" * 60)
print("GEMINI API KEY TEST")
print("=" * 60)

if not GEMINI_API_KEY:
    print("❌ GEMINI_API_KEY environment variable was NOT found.")
    print()
    print("Check your environment variable.")
    raise SystemExit(1)

print("✅ GEMINI_API_KEY found")
print(f"   Length: {len(GEMINI_API_KEY)}")
print(f"   Starts with: {GEMINI_API_KEY[:6]}...")
print(f"   Ends with: ...{GEMINI_API_KEY[-4:]}")
print()


# ============================================================
# 2. Configure Gemini
# ============================================================

try:
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ genai.configure() succeeded")
except Exception as e:
    print("❌ genai.configure() failed")
    print(type(e).__name__)
    print(str(e))
    raise SystemExit(1)


# ============================================================
# 3. Test model creation
# ============================================================

try:
    model = genai.GenerativeModel("gemini-2.5-flash")
    print("✅ Model initialized: gemini-2.5-flash")
except Exception as e:
    print("❌ Model initialization failed")
    print(type(e).__name__)
    print(str(e))
    raise SystemExit(1)


# ============================================================
# 4. Actually call Gemini
# ============================================================

try:
    print()
    print("Sending test request...")

    response = model.generate_content(
        "Reply with exactly: GEMINI TEST SUCCESS",
        generation_config={
            "temperature": 0
        }
    )

    print()
    print("✅ API REQUEST SUCCESSFUL")
    print("-" * 60)
    print(response.text)
    print("-" * 60)

except Exception as e:
    print()
    print("❌ API REQUEST FAILED")
    print("-" * 60)
    print(f"Exception type: {type(e).__name__}")
    print(f"Error: {e}")
    print("-" * 60)

    # Try to expose additional information
    if hasattr(e, "args"):
        print()
        print("Exception arguments:")
        print(e.args)

    raise