from agent import create_agent

def main():
    """Main entry point for the agent"""
    print("AI Agent with DuckDuckGo Search")
    print("Type 'quit', 'exit', or 'bye' to exit")
    print("-" * 50)
    
    try:
        agent = create_agent()
        print("Agent initialized successfully!")
        
        # Display model info based on provider
        if hasattr(agent, 'config'):
            provider = agent.config.get('provider', 'openrouter')
            if provider == 'claude_code':
                model = agent.config.get('claude_code', {}).get('model', 'default Claude model')
                print(f"Using Claude Code provider with model: {model}")
            else:
                print(f"Using OpenRouter provider with model: {agent.config['openrouter']['model']}")
                print("Note: Make sure to set your OpenRouter API key in config.yaml")
        
        print("-" * 50)
    except Exception as e:
        print(f"Error initializing agent: {e}")
        print("Make sure you have:")
        print("1. Set your API key in config.yaml (OpenRouter) or installed Claude Code CLI")
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
            
            print("Agent: Thinking...")
            response = agent.run(user_input)
            print(f"Agent: {response}")
            
        except KeyboardInterrupt:
            print("\n\nExiting...")
            break
        except Exception as e:
            print(f"Error: {e}")
            print("Please try again or type 'quit' to exit.")

if __name__ == "__main__":
    main()