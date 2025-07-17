import time
import threading
import sys
from orchestrator import TaskOrchestrator

class OrchestratorCLI:
    def __init__(self):
        self.orchestrator = TaskOrchestrator()
        self.start_time = None
        self.running = False
        
        # Extract model name for display
        model_full = self.orchestrator.config['openrouter']['model']
        # Extract model name (e.g., "google/gemini-2.5-flash-preview-05-20" -> "GEMINI-2.5-FLASH")
        if '/' in model_full:
            model_name = model_full.split('/')[-1]
        else:
            model_name = model_full
        
        # Clean up model name for display
        model_parts = model_name.split('-')
        # Take first 3 parts for cleaner display (e.g., gemini-2.5-flash)
        clean_name = '-'.join(model_parts[:3]) if len(model_parts) >= 3 else model_name
        self.model_display = clean_name.upper() + " HEAVY"
        
    def clear_screen(self):
        """Properly clear the entire screen"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def format_time(self, seconds):
        """Format seconds into readable time string"""
        if seconds < 60:
            return f"{int(seconds)}S"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}M{secs}S"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}H{minutes}M"
    
    def create_progress_bar(self, status):
        """Create progress visualization based on status"""
        # ANSI color codes
        ORANGE = '\033[38;5;208m'  # Orange color
        RED = '\033[91m'           # Red color
        RESET = '\033[0m'          # Reset color
        
        if status == "QUEUED":
            return "○ " + "·" * 70
        elif status == "INITIALIZING...":
            return f"{ORANGE}◐{RESET} " + "·" * 70
        elif status == "PROCESSING...":
            # Animated processing bar in orange
            dots = f"{ORANGE}:" * 10 + f"{RESET}" + "·" * 60
            return f"{ORANGE}●{RESET} " + dots
        elif status == "COMPLETED":
            return f"{ORANGE}●{RESET} " + f"{ORANGE}:" * 70 + f"{RESET}"
        elif status.startswith("FAILED"):
            return f"{RED}✗{RESET} " + f"{RED}×" * 70 + f"{RESET}"
        else:
            return f"{ORANGE}◐{RESET} " + "·" * 70
    
    def update_display(self):
        """Update the console display with current status"""
        if not self.running:
            return
            
        # Calculate elapsed time
        elapsed = time.time() - self.start_time if self.start_time else 0
        time_str = self.format_time(elapsed)
        
        # Get current progress
        progress = self.orchestrator.get_progress_status()
        
        # Clear screen properly
        self.clear_screen()
        
        # Header with dynamic model name
        print(self.model_display)
        if self.running:
            print(f"● RUNNING • {time_str}")
        else:
            print(f"● COMPLETED • {time_str}")
        print()
        
        # Agent status lines
        for i in range(self.orchestrator.num_agents):
            status = progress.get(i, "QUEUED")
            progress_bar = self.create_progress_bar(status)
            print(f"AGENT {i+1:02d}  {progress_bar}")
        
        print()
        sys.stdout.flush()
    
    def progress_monitor(self):
        """Monitor and update progress display in separate thread"""
        while self.running:
            self.update_display()
            time.sleep(1.0)  # Update every 1 second (reduced flicker)
    
    def run_task(self, user_input):
        """Run orchestrator task with live progress display"""
        self.start_time = time.time()
        self.running = True
        
        # Start progress monitoring in background thread
        progress_thread = threading.Thread(target=self.progress_monitor, daemon=True)
        progress_thread.start()
        
        try:
            # Run the orchestrator
            result = self.orchestrator.orchestrate(user_input)
            
            # Stop progress monitoring
            self.running = False
            
            # Final display update
            self.update_display()
            
            # Show results
            print("=" * 80)
            print("FINAL RESULTS")
            print("=" * 80)
            print()
            print(result)
            print()
            print("=" * 80)
            
            return result
            
        except Exception as e:
            self.running = False
            self.update_display()
            print(f"\nError during orchestration: {str(e)}")
            return None
    
    def interactive_mode(self):
        """Run interactive CLI session"""
        print("Multi-Agent Orchestrator")
        print(f"Configured for {self.orchestrator.num_agents} parallel agents")
        print("Type 'quit', 'exit', or 'bye' to exit")
        print("-" * 50)
        
        try:
            orchestrator_config = self.orchestrator.config['openrouter']
            print(f"Using model: {orchestrator_config['model']}")
            print("Orchestrator initialized successfully!")
            print("Note: Make sure to set your OpenRouter API key in config.yaml")
            print("-" * 50)
        except Exception as e:
            print(f"Error initializing orchestrator: {e}")
            print("Make sure you have:")
            print("1. Set your OpenRouter API key in config.yaml")
            print("2. Installed all dependencies with: pip install -r requirements.txt")
            return
        
        while True:
            try:
                user_input = input("\nUser: ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'bye']:
                    print("Goodbye!")
                    break
                
                if not user_input:
                    print("Please enter a question or command.")
                    continue
                
                print("\nOrchestrator: Starting multi-agent analysis...")
                print()
                
                # Run task with live progress
                result = self.run_task(user_input)
                
                if result is None:
                    print("Task failed. Please try again.")
                
            except KeyboardInterrupt:
                print("\n\nExiting...")
                break
            except Exception as e:
                print(f"Error: {e}")
                print("Please try again or type 'quit' to exit.")

def main():
    """Main entry point for the orchestrator CLI"""
    cli = OrchestratorCLI()
    cli.interactive_mode()

if __name__ == "__main__":
    main()
