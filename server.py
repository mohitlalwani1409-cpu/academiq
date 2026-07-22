#!/usr/bin/env python3
import http.server
import socketserver
import urllib.request
import urllib.error
import json
import os
import mimetypes
import time
import re
import math

PORT = 3000

# Paste your API key here, or set the ANTHROPIC_API_KEY environment variable.
# If left as "YOUR_API_KEY_HERE" or empty, the server runs in Simulator Mode (no key needed!).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "YOUR_API_KEY_HERE")

class DocumentRetriever:
    def __init__(self, kb_dir="knowledge_base"):
        self.kb_dir = kb_dir
        self.chunks = []
        self.stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were',
            'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'about', 'against',
            'through', 'during', 'before', 'after', 'above', 'below', 'from', 'up',
            'down', 'in', 'out', 'off', 'over', 'under', 'again', 'further', 'then',
            'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any',
            'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
            'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's',
            't', 'can', 'will', 'just', 'don', 'should', 'now', 'i', 'me', 'my',
            'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours',
            'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her',
            'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their',
            'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this', 'that',
            'these', 'those', 'am', 'been', 'have', 'has', 'had', 'do', 'does', 'did'
        }
        self.load_documents()

    def load_documents(self):
        if not os.path.exists(self.kb_dir):
            print("Knowledge base directory '{}' not found.".format(self.kb_dir))
            return
        
        for filename in os.listdir(self.kb_dir):
            if filename.endswith(".txt"):
                path = os.path.join(self.kb_dir, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    # Split into chunks by double newline
                    raw_chunks = content.split("\n\n")
                    for rc in raw_chunks:
                        # Clean up decorative separator lines (like ==== or ----)
                        lines = rc.split("\n")
                        cleaned_lines = [line.strip() for line in lines if not re.match(r'^[=\-_*#\s\t]+$', line.strip())]
                        rc_clean = "\n".join(cleaned_lines).strip()
                        
                        # Ignore short headers or empty lines
                        if len(rc_clean) < 40:
                            continue
                        
                        words = self.tokenize(rc_clean)
                        if words:
                            self.chunks.append({
                                "source": filename,
                                "text": rc_clean,
                                "words": words
                            })
                except Exception as e:
                    print("Error loading {}: {}".format(filename, e))
        print("Loaded {} knowledge base chunks from '{}'".format(len(self.chunks), self.kb_dir))

    def tokenize(self, text):
        words = re.findall(r'\b\w+\b', text.lower())
        return [w for w in words if w not in self.stop_words]

    def retrieve(self, query, threshold=0.1):
        query_words = self.tokenize(query)
        if not query_words:
            return None, 0.0
        
        best_chunk = None
        best_score = 0.0
        
        for chunk in self.chunks:
            query_set = set(query_words)
            chunk_set = set(chunk["words"])
            intersection = query_set.intersection(chunk_set)
            
            if not intersection:
                continue
            
            # Simple Cosine similarity approximation
            score = len(intersection) / (math.sqrt(len(query_set)) * math.sqrt(len(chunk_set)))
            
            # Boost score for multi-word phrase matches in context
            phrase_matches = 0
            for i in range(len(query_words) - 1):
                phrase = query_words[i] + " " + query_words[i+1]
                if phrase in chunk["text"].lower():
                    phrase_matches += 1
            
            score += phrase_matches * 0.15
            
            if score > best_score:
                best_score = score
                best_chunk = chunk
                
        if best_chunk and best_score >= threshold:
            return best_chunk, best_score
        return None, 0.0

# Initialize Retriever globally
RETRIEVER = DocumentRetriever()


def get_mock_response(system_prompt, message):
    # Simulate a network delay of 0.8 seconds so the frontend's typing indicator works realistically
    time.sleep(0.8)
    
    msg_lower = message.lower().strip()
    sys_lower = system_prompt.lower() if system_prompt else ""
    
    # Topic detection from system prompt
    topic = "general"
    if "study strategies" in sys_lower:
        topic = "study"
    elif "exam preparation" in sys_lower:
        topic = "exams"
    elif "career and major" in sys_lower:
        topic = "career"
    elif "academic writing" in sys_lower:
        topic = "writing"
    elif "wellbeing and managing" in sys_lower:
        topic = "stress"

    # Specific responses based on keywords
    if any(k in msg_lower for k in ["schedule", "plan", "calendar"]):
        return (
            "Creating an effective study schedule is key to academic success. Here is a recommended approach:\n\n"
            "1. **Audit your time**: List all your fixed commitments (classes, work, sleep) to find your available study blocks.\n"
            "2. **Prioritize tasks**: Rank your subjects by difficulty or upcoming deadlines.\n"
            "3. **Use time-blocking**: Assign specific subjects to specific hours rather than just writing a vague checklist.\n"
            "4. **Build in breaks**: Use the Pomodoro technique (50 minutes of study followed by a 10-minute break) to maintain high concentration.\n\n"
            "Would you like me to help you design a specific 7-day revision plan for one of your classes?"
        )
    elif any(k in msg_lower for k in ["exam", "test", "revision", "finals", "quiz"]):
        return (
            "Preparing for exams requires active engagement rather than just passive reading. Here are three highly effective techniques:\n\n"
            "• **Active Recall**: Close your book and write down everything you remember about a topic. This strengthens neural pathways.\n"
            "• **Spaced Repetition**: Review the material at increasing intervals (e.g., 1 day, 3 days, 7 days later) to move information into your long-term memory.\n"
            "• **Practice Papers**: Simulate exam conditions by doing past tests with a timer. This builds both speed and confidence.\n\n"
            "Which exam style (multiple choice, essay-based, or problem-solving) are you preparing for?"
        )
    elif any(k in msg_lower for k in ["major", "career", "job", "college", "university"]):
        return (
            "Choosing a major or career path is a journey of self-discovery and market research. Consider these steps:\n\n"
            "• **Identify Interests & Skills**: What subjects do you naturally enjoy or excel at?\n"
            "• **Explore Careers**: Look at job market trends, average salaries, and typical day-to-day responsibilities in fields of interest.\n"
            "• **Try Introductory Classes**: Take elective courses or talk to seniors/professors in those majors.\n"
            "• **Seek Experience**: Internships, volunteering, or job shadowing can provide invaluable clarity.\n\n"
            "What fields of study are you currently torn between?"
        )
    elif any(k in msg_lower for k in ["write", "paper", "essay", "cite", "apa", "mla", "chicago"]):
        return (
            "Writing a strong research paper is a step-by-step process. Here is a framework to guide you:\n\n"
            "1. **Formulate a clear thesis statement**: This is the core argument of your paper and should be stated clearly in your introduction.\n"
            "2. **Structure logically**: Use the standard academic structure (Introduction, Literature Review, Methodology, Analysis, and Conclusion).\n"
            "3. **Cite sources correctly**: Ensure every external idea is referenced using your required style (APA, MLA, Chicago).\n"
            "4. **Draft first, edit later**: Don't try to make it perfect on your first pass. Get your ideas down first, then refine.\n\n"
            "What is the topic of the paper you are currently working on?"
        )
    elif any(k in msg_lower for k in ["stress", "burnout", "wellbeing", "anxiety", "tired", "sad", "overwhelmed"]):
        return (
            "Academic stress and burnout are very real challenges. Remember that your mental and physical health are far more important than any grade. Here are some strategies to manage pressure:\n\n"
            "• **Set boundaries**: Establish clear times when you stop studying and relax.\n"
            "• **Prioritize sleep & nutrition**: A sleep-deprived brain is significantly less efficient and more prone to anxiety.\n"
            "• **Break tasks down**: Large projects can feel overwhelming. Break them into micro-steps to reduce starting friction.\n"
            "• **Reach out**: Don't hesitate to speak to friends, family, or your university's counseling services.\n\n"
            "How are you feeling right now? Remember, taking a break is part of the work."
        )
    elif any(k in msg_lower for k in ["focus", "concentrate", "distract", "attention"]):
        return (
            "Staying focused is a skill that can be built over time. Here are some techniques to optimize your environment and mind:\n\n"
            "• **Minimize Distractions**: Put your phone in another room or use website blockers during study sessions.\n"
            "• **The Pomodoro Technique**: Work for 25 minutes, then take a 5-minute break. After 4 cycles, take a longer 15-30 minute break.\n"
            "• **Single-Tasking**: Multi-tasking is a myth. Pick one task and give it your full attention.\n"
            "• **Study Space**: Have a dedicated workspace that is clean and well-lit. Your brain will begin to associate this space with focus.\n\n"
            "What is your biggest distraction when you sit down to study?"
        )
    elif any(k in msg_lower for k in ["gpa", "grades", "grad school"]):
        return (
            "GPAs are important for specific goals, but they don't define your intelligence or capability.\n\n"
            "For graduate school, a GPA of 3.0 is often the minimum requirement, while competitive programs look for a 3.5 or higher. However, schools also look at your letters of recommendation, research experience, and personal statement.\n\n"
            "Are you looking to improve your GPA, or are you currently applying to grad school?"
        )
    elif "hello" in msg_lower or "hi" in msg_lower or "hey" in msg_lower:
        return (
            "Hello! I am AcademiQ, your Academic Advisor chatbot. How is your semester going?"
        )

    # General Topic-based defaults if no keywords matched
    if topic == "study":
        return (
            "As your Study Strategies Specialist, I recommend starting with small, manageable habits.\n\n"
            "To study effectively, make sure you are actively recalling information rather than just rereading notes. "
            "For example, try drawing mind maps or explaining the concepts aloud to someone else.\n\n"
            "What subject are you currently studying?"
        )
    elif topic == "exams":
        return (
            "As your Exam Prep Coach, I want to remind you that mock tests are your best tool.\n\n"
            "Try to practice under timed conditions to get used to the pace of the actual exam. "
            "Also, don't cram the night before—sleep is crucial for memory consolidation.\n\n"
            "What kind of exam do you have coming up?"
        )
    elif topic == "career":
        return (
            "As your Career & Major Advisor, I suggest connecting with your university's career services.\n\n"
            "They can help you run mock interviews, review your resume, and connect you with alumni. "
            "Would you like to discuss resume writing, interview preparation, or exploring internships?"
        )
    elif topic == "writing":
        return (
            "As your Writing & Research Guide, I recommend starting every writing session with a free-write "
            "to get your thoughts flowing. Don't worry about editing or grammar in your first draft.\n\n"
            "What is the prompt or topic of your current writing assignment?"
        )
    elif topic == "stress":
        return (
            "As your Wellbeing & Stress Support guide, please take a deep breath.\n\n"
            "It is completely normal to feel overwhelmed, but you don't have to carry it all at once. "
            "Make sure you take at least 30 minutes today to do something you enjoy, completely unrelated to academics.\n\n"
            "What is one small thing you can do to take care of yourself today?"
        )
    else:
        return (
            "Hello! I am AcademiQ, your Academic Advisor. I am here to help you navigate your academic journey.\n\n"
            "You can choose a specialized topic from the sidebar on the left, or ask me questions about:\n"
            "• Building effective study schedules\n"
            "• Exam preparation strategies\n"
            "• Choosing a college major or career path\n"
            "• Writing research papers & essays\n"
            "• Managing stress and avoiding burnout\n\n"
            "How can I assist you today?"
        )

class AcademiqProxyHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/api/chat":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            # Parse payload for RAG retrieval
            try:
                payload = json.loads(post_data.decode('utf-8'))
                system_prompt = payload.get("system", "")
                messages = payload.get("messages", [])
                user_message = messages[-1].get("content", "") if messages else ""
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": f"Invalid JSON payload: {str(e)}"}}).encode('utf-8'))
                return

            # Perform RAG retrieval
            matched_chunk, score = RETRIEVER.retrieve(user_message)
            sources = []
            if matched_chunk:
                sources = [matched_chunk["source"]]
                print("RAG Retrieval Match: {} (score: {:.3f})".format(matched_chunk["source"], score))

            # Check if key is configured
            is_mock_mode = (not ANTHROPIC_API_KEY) or (ANTHROPIC_API_KEY.strip() in ["", "YOUR_API_KEY_HERE"])
            
            if is_mock_mode:
                try:
                    if matched_chunk:
                        # Simulate a network delay of 0.8 seconds so the frontend's typing indicator works realistically
                        time.sleep(0.8)
                        source_display = matched_chunk["source"].replace("_", " ").replace(".txt", "").title()
                        mock_text = (
                            "Based on the official **{}**, here is the relevant policy:\n\n"
                            "{}\n\n"
                            "Let me know if you have any questions or need further clarification on this policy."
                        ).format(source_display, matched_chunk["text"])
                    else:
                        mock_text = get_mock_response(system_prompt, user_message)
                    
                    mock_response_json = {
                        "content": [
                            {
                                "type": "text",
                                "text": mock_text
                            }
                        ],
                        "sources": sources
                    }
                    
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(mock_response_json).encode('utf-8'))
                except Exception as e:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "error": {
                            "message": f"Simulator error: {str(e)}"
                        }
                    }).encode('utf-8'))
                return

            # Live Proxy Mode
            # Inject context into system prompt if RAG matched
            if matched_chunk:
                augmented_system = (
                    "{}\n\n"
                    "[CRITICAL CONTEXT FROM UNIVERSITY POLICIES (Document: {})]:\n"
                    "{}\n\n"
                    "You MUST use the above official policies to answer the user's question, citing the details of the policy if relevant. "
                    "Do not mention that you were given context or document uploads, answer naturally as AcademiQ advisor."
                ).format(system_prompt, matched_chunk["source"], matched_chunk["text"])
                payload["system"] = augmented_system
                post_data = json.dumps(payload).encode('utf-8')

            # Prepare request to Anthropic API
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            }
            
            # Forward the request to Anthropic
            req = urllib.request.Request(url, data=post_data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req) as response:
                    res_body = response.read()
                    
                    # If RAG matched, inject the source list into the response JSON
                    if matched_chunk:
                        try:
                            res_json = json.loads(res_body.decode('utf-8'))
                            res_json["sources"] = sources
                            res_body = json.dumps(res_json).encode('utf-8')
                        except Exception as ex:
                            print("Error injecting source info: {}".format(ex))

                    self.send_response(response.status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(res_body)
            except urllib.error.HTTPError as e:
                res_body = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(res_body)
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": {
                        "message": f"Proxy error: {str(e)}"
                    }
                }).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

# Fix for Windows MIME types registration
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

# Allow address reuse to avoid port-in-use errors when restarting quickly
socketserver.TCPServer.allow_reuse_address = True

if __name__ == "__main__":
    handler = AcademiqProxyHandler
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print("========================================")
        print("  AcademiQ is running (Python Server)!")
        print("  Open: http://localhost:{}".format(PORT))
        print("========================================")
        
        # Check if running in Simulator Mode or live API Proxy mode
        if (not ANTHROPIC_API_KEY) or (ANTHROPIC_API_KEY.strip() in ["", "YOUR_API_KEY_HERE"]):
            print("STATUS: Running in SIMULATOR Mode (Keyless)")
            print("The chat will generate smart offline responses.")
            print("To connect to the live Claude API later, paste your key in server.py")
        else:
            print("STATUS: Running in LIVE PROXY Mode")
            print("Forwarding requests directly to Anthropic Claude API.")
        print("========================================")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")
