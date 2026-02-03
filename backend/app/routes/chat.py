# app/routes/chat.py

import os
import openai
import anthropic
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import logging
import json
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)

# Initialize OpenAI client
def get_openai_client():
    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found in configuration")
    return openai.OpenAI(api_key=api_key)

# Initialize Claude client
def get_claude_client():
    api_key = current_app.config.get('CLAUDE_API_KEY')
    if not api_key:
        raise ValueError("CLAUDE_API_KEY not found in configuration")
    return anthropic.Anthropic(api_key=api_key)

@chat_bp.route('/chat', methods=['POST'], strict_slashes=False)
@jwt_required()
def chat():
    """
    Handle chat requests from the Wizard component
    Updated from basic echo to full OpenAI integration
    """
    try:
        # Get current user
        current_user_id = get_jwt_identity()
        
        # Get request data
        payload = request.get_json() or {}
        user_message = payload.get('message', '').strip()
        doc_type = payload.get('docType', 'market_analysis')
        detailed = payload.get('detailed', True)
        system_prompt = payload.get('systemPrompt', '')
        phase = payload.get('phase', 1)
        
        if not user_message:
            return jsonify({'error': 'Message is required'}), 400
        
        # If no system prompt provided, use a default one
        if not system_prompt:
            system_prompt = "You are a helpful business analyst assistant. Provide detailed, professional advice."
        
        logger.info(f"Chat request from user {current_user_id}: doc_type={doc_type}, phase={phase}, detailed={detailed}")
        
        # Initialize OpenAI client
        client = get_openai_client()
        
        # Prepare messages for OpenAI
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user", 
                "content": user_message
            }
        ]
        
        # Make request to OpenAI
        try:
            response = client.chat.completions.create(
                model="gpt-4o",  # Use GPT-4o or gpt-4-turbo
                messages=messages,
                max_tokens=2000,
                temperature=0.7,
                top_p=1,
                frequency_penalty=0,
                presence_penalty=0
            )
            
            # Extract the reply
            if response.choices and len(response.choices) > 0:
                reply = response.choices[0].message.content
                
                logger.info(f"OpenAI response received for user {current_user_id}")
                
                return jsonify({
                    'success': True,
                    'reply': reply,
                    'usage': {
                        'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                        'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                        'total_tokens': response.usage.total_tokens if response.usage else 0
                    }
                })
            else:
                logger.error("No choices in OpenAI response")
                return jsonify({'error': 'No response from AI'}), 500
                
        except openai.RateLimitError as e:
            logger.error(f"OpenAI rate limit error: {e}")
            return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
            
        except openai.AuthenticationError as e:
            logger.error(f"OpenAI authentication error: {e}")
            return jsonify({'error': 'API authentication failed. Please check your OpenAI API key.'}), 500
            
        except openai.APIError as e:
            logger.error(f"OpenAI API error: {e}")
            return jsonify({'error': f'API error: {str(e)}'}), 500
            
        except Exception as e:
            logger.error(f"Unexpected OpenAI error: {e}")
            return jsonify({'error': f'Unexpected error: {str(e)}'}), 500
    
    except Exception as e:
        logger.error(f"Chat endpoint error: {e}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

# NEW: Enhanced main chat route for FloatingAI with statistical analysis support
@chat_bp.route('', methods=['POST'])
@jwt_required()
def chat_main():
    """
    Enhanced main chat route that handles both Wizard and FloatingAI requests
    Supports statistical analysis context and tool-specific responses
    """
    try:
        current_user_id = get_jwt_identity()
        payload = request.get_json() or {}
        
        # Check if this is a FloatingAI request (has tool and context)
        tool = payload.get('tool', '').lower()
        context = payload.get('context', {})
        
        if tool and context:
            # This is a FloatingAI request - handle with enhanced functionality
            return handle_floating_ai_chat(payload, current_user_id)
        else:
            # This is a Wizard request - use existing functionality
            return chat()
            
    except Exception as e:
        logger.error(f"Chat main endpoint error: {e}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

def handle_floating_ai_chat(payload, user_id):
    """
    Handle FloatingAI chat requests with tool-specific context awareness
    """
    try:
        message = payload.get('message', '').strip()
        tool = payload.get('tool', 'unknown').lower()
        context = payload.get('context', {})
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Get context data
        page = context.get('page', 'unknown')
        form_data = context.get('formData', {})
        statistical_context = context.get('statisticalContext', None)
        
        logger.info(f"FloatingAI request from user {user_id}: tool={tool}, page={page}")
        
        # Generate AI response based on tool type
        if tool == 'statistics':
            response_text = generate_statistical_response(message, statistical_context, user_id)
        elif tool in ['a3', 'finy', 'sipoc']:
            response_text = generate_form_response(message, tool, form_data, user_id)
        else:
            response_text = generate_general_response(message, tool, context, user_id)
        
        return jsonify({
            'success': True,
            'response': response_text,
            'tool': tool,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"FloatingAI chat error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to generate AI response',
            'fallback': True
        }), 500

def generate_statistical_response(message, statistical_context, user_id):
    """
    Generate AI response for statistical analysis with context awareness
    """
    try:
        # Build context-aware prompt
        system_prompt = build_statistical_system_prompt(statistical_context)
        
        # Try Claude first for statistical analysis (better at reasoning)
        try:
            claude_client = get_claude_client()
            response = claude_client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1000,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": message
                    }
                ]
            )
            return response.content[0].text
            
        except Exception as claude_error:
            logger.warning(f"Claude error, falling back to OpenAI: {claude_error}")
            
            # Fallback to OpenAI if Claude fails
            openai_client = get_openai_client()
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message}
                ],
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Statistical AI error: {str(e)}")
        return generate_statistical_fallback_response(message, statistical_context)

def build_statistical_system_prompt(statistical_context):
    """
    Build context-aware system prompt for statistical analysis
    """
    base_prompt = """You are Kii, an expert statistical analysis assistant. You help users choose appropriate statistical methods, interpret results, and guide them through data analysis workflows.

Your expertise includes:
- Descriptive statistics and data exploration
- Hypothesis testing (t-tests, ANOVA, chi-square)
- Correlation and regression analysis
- Data visualization recommendations
- Statistical significance and effect sizes
- Choosing appropriate tests based on data types

Always provide practical, actionable guidance and explain statistical concepts in simple terms."""

    if not statistical_context:
        return base_prompt + "\n\nThe user hasn't uploaded data yet. Encourage them to upload a CSV file and explain what you can help with once they have data."
    
    dataset = statistical_context.get('dataset', {})
    analysis = statistical_context.get('analysis', {})
    recommendations = statistical_context.get('recommendations', [])
    
    if not dataset.get('hasData'):
        return base_prompt + "\n\nThe user hasn't uploaded data yet. Encourage them to upload a CSV file."
    
    context_info = f"""
Current Dataset Context:
- File: {dataset.get('fileName', 'Unknown')}
- Rows: {dataset.get('rowCount', 0)}
- Columns: {dataset.get('columnCount', 0)}
- Numeric variables: {', '.join(dataset.get('numericColumns', []))}
- Categorical variables: {', '.join(dataset.get('categoricalColumns', []))}

Current Analysis:
- Goal: {analysis.get('goal', 'Not set')}
- Target variable: {analysis.get('targetCol', 'Not selected')}
- Group variable: {analysis.get('groupCol', 'Not selected')}

Recommended methods: {', '.join(recommendations)}

Use this context to provide specific, relevant guidance. Reference the actual variable names and data structure in your responses."""

    return base_prompt + context_info

def generate_form_response(message, tool, form_data, user_id):
    """
    Generate AI response for form-based tools (A3, FinY, SIPOC)
    """
    try:
        system_prompt = build_form_system_prompt(tool, form_data)
        
        # Use OpenAI for form assistance
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            max_tokens=800,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Form AI error: {str(e)}")
        return generate_form_fallback_response(message, tool, form_data)

def build_form_system_prompt(tool, form_data):
    """
    Build system prompt for form-based tools
    """
    prompts = {
        'a3': """You are Kii, an expert A3 Problem Solving assistant. Help users fill out their A3 form by extracting information from conversations and providing guidance on problem-solving methodology.

A3 sections: Project Title, Problem Owner, Team Members, Background, Problem Statement, Business Impact, Current State, Goal Statement, Target State, Results, Lessons Learned, Next Steps.

Extract relevant information and suggest what to fill in next.""",
        
        'finy': """You are Kii, a FinY (Financial Analysis) assistant. Help users calculate financial benefits and ROI for their improvement projects.

FinY sections: Project Title, Baseline Performance, Target Performance, Timeframe, Investment Cost, Expected Savings, ROI Calculation.

Focus on quantifiable financial metrics and business value.""",
        
        'sipoc': """You are Kii, a SIPOC (Suppliers, Inputs, Process, Outputs, Customers) assistant. Help users map their business processes systematically.

SIPOC sections: Suppliers, Inputs, Process Steps, Outputs, Customers.

Guide users through each section methodically."""
    }
    
    base_prompt = prompts.get(tool, prompts['a3'])
    
    if form_data:
        filled_fields = [f"{k}: {v}" for k, v in form_data.items() if v and v.strip()]
        if filled_fields:
            base_prompt += f"\n\nCurrent form data:\n" + "\n".join(filled_fields)
    
    return base_prompt

def generate_general_response(message, tool, context, user_id):
    """
    Generate AI response for general/unknown tools
    """
    try:
        system_prompt = f"You are Kii, a helpful assistant for the {tool} tool. Provide guidance and support for the user's questions."
        
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            max_tokens=600,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"General AI error: {str(e)}")
        return f"I'm here to help with {tool}! Could you tell me more about what you're working on?"

def generate_statistical_fallback_response(message, statistical_context):
    """
    Fallback response for statistical analysis when AI APIs fail
    """
    message_lower = message.lower()
    
    if not statistical_context or not statistical_context.get('dataset', {}).get('hasData'):
        return "I'd love to help with your statistical analysis! Please upload a dataset first so I can provide specific guidance based on your data structure."
    
    dataset = statistical_context.get('dataset', {})
    
    if 'correlation' in message_lower or 'relationship' in message_lower:
        if len(dataset.get('numericColumns', [])) >= 2:
            return f"For correlation analysis, I can see you have {len(dataset.get('numericColumns', []))} numeric columns. Set your goal to 'Association / Relationships' to compute Pearson correlations between all numeric pairs."
        else:
            return "For correlation analysis, you need at least 2 numeric variables. Consider converting categorical variables to numeric if appropriate."
    
    if 'compare' in message_lower or 'group' in message_lower:
        if len(dataset.get('numericColumns', [])) >= 1 and len(dataset.get('categoricalColumns', [])) >= 1:
            return "For group comparisons, set your goal to 'Compare Groups', then select a numeric target variable and a categorical grouping variable."
        else:
            return "For group comparisons, you need at least one numeric variable (outcome) and one categorical variable (groups)."
    
    if 'describe' in message_lower or 'summary' in message_lower:
        return "For descriptive statistics, set your goal to 'Describe / Summarize'. This will provide summary statistics for numeric variables and frequency tables for categorical variables."
    
    return f"I can help you analyze your dataset with {dataset.get('rowCount', 0)} rows and {dataset.get('columnCount', 0)} columns. What type of analysis are you interested in?"

def generate_form_fallback_response(message, tool, form_data):
    """
    Fallback response for form tools when AI APIs fail
    """
    return f"I'm here to help you complete your {tool.upper()} form. You can tell me about your project details and I'll help organize the information. What would you like to work on?"

# NEW: Additional endpoint for statistical analysis insights
@chat_bp.route('/statistical-insights', methods=['POST'])
@jwt_required()
def statistical_insights():
    """
    Dedicated endpoint for generating statistical insights from analysis results
    """
    try:
        data = request.get_json()
        user_id = get_jwt_identity()
        
        analysis_results = data.get('results', {})
        dataset_info = data.get('dataset', {})
        analysis_goal = data.get('goal', 'describe')
        
        # Generate insights using Claude (better at statistical reasoning)
        insights = generate_analysis_insights(analysis_results, dataset_info, analysis_goal)
        
        return jsonify({
            'success': True,
            'insights': insights,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Statistical insights error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to generate insights'
        }), 500

def generate_analysis_insights(results, dataset_info, goal):
    """
    Generate statistical insights from analysis results
    """
    try:
        system_prompt = """You are a statistical expert. Analyze the provided statistical results and generate clear, actionable insights. Focus on:

1. What the results mean in practical terms
2. Statistical significance and effect sizes
3. Recommendations for next steps
4. Potential limitations or caveats
5. Business implications

Explain everything in simple, non-technical language."""

        context = f"""
Dataset: {dataset_info.get('fileName', 'Unknown')} ({dataset_info.get('rowCount', 0)} rows)
Analysis Goal: {goal}
Results: {json.dumps(results, indent=2)}
"""

        try:
            claude_client = get_claude_client()
            response = claude_client.messages.create(
                model="claude-3-sonnet-20240229",
                max_tokens=1200,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Please analyze these statistical results and provide insights:\n\n{context}"
                    }
                ]
            )
            return response.content[0].text
        except:
            # Fallback to OpenAI
            client = get_openai_client()
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Please analyze these statistical results and provide insights:\n\n{context}"}
                ],
                max_tokens=1200,
                temperature=0.7
            )
            return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Insights generation error: {str(e)}")
        return "Analysis complete! Review your results above. Consider running additional analyses or visualizations to explore your data further."

@chat_bp.route('/test', methods=['GET'])
def test_chat():
    """
    Test endpoint to verify chat route is working
    """
    return jsonify({
        'message': 'Chat route is working',
        'openai_configured': bool(current_app.config.get('OPENAI_API_KEY')),
        'claude_configured': bool(current_app.config.get('CLAUDE_API_KEY'))
    })

@chat_bp.route('/models', methods=['GET'])
@jwt_required()
def get_available_models():
    """
    Get available OpenAI models
    """
    try:
        client = get_openai_client()
        models = client.models.list()
        
        # Filter for chat models
        chat_models = [
            model.id for model in models.data 
            if 'gpt' in model.id.lower() and any(x in model.id for x in ['3.5', '4'])
        ]
        
        return jsonify({
            'success': True,
            'models': sorted(chat_models)
        })
        
    except Exception as e:
        logger.error(f"Error fetching models: {e}")
        return jsonify({'error': str(e)}), 500
