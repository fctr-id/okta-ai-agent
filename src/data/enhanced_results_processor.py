"""
Enhanced Results Processor Agent with Pandas Integration for Okta AI Agent.

This module provides advanced data processing capabilities:
- Pandas-based data analysis and transformation
- Advanced aggregation and statistical analysis
- Memory-efficient processing for large datasets
- Enhanced formatting with data insights
- Intelligent data visualization recommendations
"""

import pandas as pd
import numpy as np
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union, Tuple
from pydantic_ai import Agent
import json
import re
from datetime import datetime, timedelta
import os
import sys

# Add the project root to Python path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from src.core.model_picker import ModelConfig, ModelType
    from src.utils.logging import get_logger
except ImportError as e:
    print(f"Warning: Could not import project modules: {e}")
    print("Enhanced results processor will use fallback configurations")
    
    # Fallback logger
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Fallback model config
    class ModelType:
        REASONING = "reasoning"
        CODING = "coding"
    
    class ModelConfig:
        @staticmethod
        def get_model(model_type):
            return "gpt-4"  # Fallback model
else:
    logger = get_logger(__name__)

class EnhancedProcessingResponse(BaseModel):
    """Enhanced output structure for the Results Processor with pandas insights."""
    display_type: str = Field(description="Type of display format (markdown, table)")
    content: Any = Field(description="Formatted content for display")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Enhanced metadata with analytics")
    processing_code: Optional[str] = Field(default=None, description="Pandas-enhanced processing code")
    data_insights: Optional[Dict[str, Any]] = Field(default=None, description="Statistical insights from pandas analysis")
    visualization_suggestions: Optional[List[str]] = Field(default=None, description="Recommended visualizations")

class PandasEnhancedResultsProcessor:
    """Enhanced Results Processor Agent with pandas integration."""
    
    def __init__(self, model_config: Optional[ModelConfig] = None):
        """Initialize the Enhanced Results Processor Agent."""
        
        # Load the LLM3 system prompt
        self.system_prompt = self._load_llm3_system_prompt()
        
        # Get the REASONING model for results processing
        model = model_config or ModelConfig.get_model(ModelType.REASONING)
        
        # Create the agent with the LLM3 system prompt
        self.agent = Agent(
            system=self.system_prompt,
            model=model  
        )
    
    def _load_llm3_system_prompt(self) -> str:
        """Load the LLM3 system prompt from file."""
        try:
            # Construct path to llm3_system_prompt.txt
            current_dir = os.path.dirname(__file__)
            # The file is in the same directory as this file
            prompt_path = os.path.join(current_dir, 'llm3_system_prompt.txt')
            
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            logger.warning("LLM3 system prompt not found, using fallback")
            return self._get_fallback_system_prompt()
    
    def _get_fallback_system_prompt(self) -> str:
        """Fallback system prompt if file not found."""
        return """You are LLM3, an expert Results Processor Agent specialized in consolidating Okta AI agent execution results.
        
        Transform complex execution results into clear, user-friendly reports that directly answer the user's query.
        
        CRITICAL: Respond with valid JSON only: {"display_type": "markdown"|"table", "content": "...", "metadata": {...}}
        
        For markdown: provide explanatory content with clear reasoning.
        For table: provide array of objects with consistent structure.
        
        Always include confidence levels and data source information in metadata."""
    
    async def process_results_with_pandas(self, query: str, results: dict, original_plan: Any, 
                                        metadata: dict = None) -> EnhancedProcessingResponse:
        """Process execution results with pandas-enhanced analytics."""
        
        if not metadata:
            metadata = {}
        
        flow_id = metadata.get("flow_id", "unknown")
        logger.info(f"[{flow_id}] Processing results with pandas enhancement for query: {query}")
        
        try:
            # Step 1: Extract and analyze data with pandas
            data_analysis = self._analyze_data_with_pandas(results, flow_id)
            
            # Step 2: Create enhanced prompt with pandas insights
            enhanced_prompt = self._create_pandas_enhanced_prompt(
                query, results, original_plan, data_analysis
            )
            
            # Step 3: Call the LLM3 agent
            response = await self.agent.run(enhanced_prompt)
            
            # Step 4: Parse response and enhance with pandas insights
            processing_response = self._parse_enhanced_response(
                response.output, data_analysis, flow_id
            )
            
            # Step 5: Add visualization suggestions
            processing_response.visualization_suggestions = self._suggest_visualizations(
                data_analysis, query
            )
            
            return processing_response
            
        except Exception as e:
            logger.error(f"[{flow_id}] Error in pandas-enhanced processing: {str(e)}")
            return self._create_error_response(str(e))
    
    def _analyze_data_with_pandas(self, results: dict, flow_id: str) -> Dict[str, Any]:
        """Analyze execution results using pandas for enhanced insights."""
        
        analysis = {
            'sql_analysis': None,
            'api_analysis': None,
            'combined_analysis': None,
            'data_quality': {},
            'statistical_summary': {},
            'patterns': [],
            'recommendations': []
        }
        
        try:
            # Analyze SQL data if available
            sql_data = results.get('sql_execution', {}).get('data', [])
            if sql_data and isinstance(sql_data, list) and len(sql_data) > 0:
                analysis['sql_analysis'] = self._analyze_sql_data_pandas(sql_data, flow_id)
            
            # Analyze API execution results if available
            execution_result = results.get('execution_result', {})
            if execution_result and execution_result.get('success'):
                api_output = execution_result.get('stdout', '')
                analysis['api_analysis'] = self._analyze_api_output_pandas(api_output, flow_id)
            
            # Combined analysis
            analysis['combined_analysis'] = self._perform_combined_analysis(
                analysis['sql_analysis'], analysis['api_analysis'], flow_id
            )
            
        except Exception as e:
            logger.warning(f"[{flow_id}] Error in pandas analysis: {str(e)}")
            analysis['error'] = str(e)
        
        return analysis
    
    def _analyze_sql_data_pandas(self, sql_data: List[Dict], flow_id: str) -> Dict[str, Any]:
        """Analyze SQL data using pandas."""
        
        try:
            # Convert to DataFrame
            df = pd.DataFrame(sql_data)
            
            if df.empty:
                return {'empty': True, 'message': 'No SQL data to analyze'}
            
            analysis = {
                'shape': df.shape,
                'columns': list(df.columns),
                'dtypes': df.dtypes.to_dict(),
                'null_counts': df.isnull().sum().to_dict(),
                'data_quality_score': self._calculate_data_quality_score(df),
                'statistical_summary': {},
                'patterns': [],
                'insights': []
            }
            
            # Statistical summary for numeric columns
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                analysis['statistical_summary'] = df[numeric_cols].describe().to_dict()
            
            # Categorical analysis
            categorical_cols = df.select_dtypes(include=['object']).columns
            for col in categorical_cols:
                value_counts = df[col].value_counts()
                analysis[f'{col}_distribution'] = value_counts.head(10).to_dict()
            
            # Detect patterns
            analysis['patterns'] = self._detect_data_patterns(df)
            
            # Generate insights
            analysis['insights'] = self._generate_dataframe_insights(df, flow_id)
            
            logger.debug(f"[{flow_id}] SQL data analysis: {df.shape[0]} rows, {df.shape[1]} columns")
            
            return analysis
            
        except Exception as e:
            logger.warning(f"[{flow_id}] Error analyzing SQL data with pandas: {str(e)}")
            return {'error': str(e)}
    
    def _analyze_api_output_pandas(self, api_output: str, flow_id: str) -> Dict[str, Any]:
        """Analyze API execution output using pandas."""
        
        try:
            # Try to extract JSON data from API output
            json_matches = re.findall(r'\{.*?\}', api_output, re.DOTALL)
            
            if not json_matches:
                return {'message': 'No structured data found in API output'}
            
            # Parse JSON objects
            parsed_data = []
            for match in json_matches:
                try:
                    data = json.loads(match)
                    if isinstance(data, dict):
                        parsed_data.append(data)
                except json.JSONDecodeError:
                    continue
            
            if not parsed_data:
                return {'message': 'No valid JSON data found in API output'}
            
            # Convert to DataFrame
            df = pd.DataFrame(parsed_data)
            
            analysis = {
                'shape': df.shape,
                'columns': list(df.columns),
                'sample_data': df.head(3).to_dict('records'),
                'data_types': df.dtypes.to_dict(),
                'unique_counts': df.nunique().to_dict(),
                'insights': self._generate_dataframe_insights(df, flow_id)
            }
            
            logger.debug(f"[{flow_id}] API data analysis: {df.shape[0]} records extracted")
            
            return analysis
            
        except Exception as e:
            logger.warning(f"[{flow_id}] Error analyzing API output: {str(e)}")
            return {'error': str(e)}
    
    def _calculate_data_quality_score(self, df: pd.DataFrame) -> float:
        """Calculate data quality score (0-100) based on completeness and consistency."""
        
        try:
            total_cells = df.size
            non_null_cells = df.count().sum()
            completeness_score = (non_null_cells / total_cells) * 100 if total_cells > 0 else 0
            
            # Additional quality checks could be added here
            # For now, use completeness as primary indicator
            
            return round(completeness_score, 2)
            
        except Exception:
            return 0.0
    
    def _detect_data_patterns(self, df: pd.DataFrame) -> List[str]:
        """Detect interesting patterns in the data."""
        
        patterns = []
        
        try:
            # Check for timestamp patterns
            for col in df.columns:
                if 'date' in col.lower() or 'time' in col.lower():
                    patterns.append(f"Temporal data detected in column '{col}'")
            
            # Check for ID patterns
            for col in df.columns:
                if 'id' in col.lower() and df[col].dtype == 'object':
                    unique_ratio = df[col].nunique() / len(df)
                    if unique_ratio > 0.9:
                        patterns.append(f"High uniqueness in '{col}' suggests identifier column")
            
            # Check for status patterns
            for col in df.columns:
                if 'status' in col.lower():
                    unique_values = df[col].unique()
                    patterns.append(f"Status column '{col}' has values: {list(unique_values)[:5]}")
            
        except Exception as e:
            patterns.append(f"Error detecting patterns: {str(e)}")
        
        return patterns
    
    def _generate_dataframe_insights(self, df: pd.DataFrame, flow_id: str) -> List[str]:
        """Generate business insights from DataFrame analysis."""
        
        insights = []
        
        try:
            # Data volume insights
            insights.append(f"Dataset contains {len(df)} records across {len(df.columns)} attributes")
            
            # Completeness insights
            null_percentages = (df.isnull().sum() / len(df) * 100).round(2)
            incomplete_cols = null_percentages[null_percentages > 0]
            if len(incomplete_cols) > 0:
                insights.append(f"Data completeness issues in {len(incomplete_cols)} columns")
            
            # Uniqueness insights
            for col in df.columns:
                unique_count = df[col].nunique()
                total_count = len(df)
                if unique_count == total_count:
                    insights.append(f"Column '{col}' has all unique values (potential identifier)")
                elif unique_count == 1:
                    insights.append(f"Column '{col}' has constant value: {df[col].iloc[0]}")
            
        except Exception as e:
            insights.append(f"Error generating insights: {str(e)}")
        
        return insights
    
    def _perform_combined_analysis(self, sql_analysis: Dict, api_analysis: Dict, 
                                 flow_id: str) -> Dict[str, Any]:
        """Perform combined analysis of SQL and API data."""
        
        combined = {
            'data_sources': [],
            'total_records': 0,
            'consistency_check': None,
            'recommendations': []
        }
        
        try:
            if sql_analysis and not sql_analysis.get('empty'):
                combined['data_sources'].append('SQL Database')
                combined['total_records'] += sql_analysis.get('shape', [0])[0]
            
            if api_analysis and not api_analysis.get('error'):
                combined['data_sources'].append('API Calls')
                combined['total_records'] += api_analysis.get('shape', [0])[0]
            
            # Generate recommendations based on available data
            if len(combined['data_sources']) == 2:
                combined['recommendations'].append(
                    "Hybrid data available - consider cross-referencing SQL and API results"
                )
            elif 'SQL Database' in combined['data_sources']:
                combined['recommendations'].append(
                    "SQL data only - consider API calls for real-time verification"
                )
            elif 'API Calls' in combined['data_sources']:
                combined['recommendations'].append(
                    "API data only - consider historical SQL data for trend analysis"
                )
            
        except Exception as e:
            logger.warning(f"[{flow_id}] Error in combined analysis: {str(e)}")
        
        return combined
    
    def _create_pandas_enhanced_prompt(self, query: str, results: Dict[str, Any], 
                                     plan: Any, data_analysis: Dict[str, Any]) -> str:
        """Create enhanced prompt with pandas insights."""
        
        # Extract basic execution information
        sql_records = len(results.get('sql_execution', {}).get('data', []))
        api_endpoints = results.get('endpoint_filtering', {}).get('filtered_count', 0)
        code_generated = results.get('llm2_code_generation', {}).get('success', False)
        code_executed = results.get('execution_result', {}).get('success', False)
        
        # Build data insights section
        insights_section = self._build_insights_section(data_analysis)
        
        # Create comprehensive prompt
        prompt = f"""
Process these comprehensive Okta AI agent execution results with enhanced analytics:

## User Query
"{query}"

## Execution Results Summary
- SQL Records Retrieved: {sql_records}
- API Endpoints Filtered: {api_endpoints}
- Code Generated: {code_generated}
- Code Executed: {code_executed}

## Enhanced Data Analytics
{insights_section}

## Complete Execution Data
{json.dumps(results, default=str, indent=2)[:8000]}...

## Task
Using the pandas-enhanced insights above, create a comprehensive response that:
1. Directly answers the user's query
2. Incorporates data quality and statistical insights
3. Provides confidence levels based on data analysis
4. Suggests actionable next steps

Respond with valid JSON only using the specified format.
"""
        
        return prompt
    
    def _build_insights_section(self, data_analysis: Dict[str, Any]) -> str:
        """Build the insights section for the prompt."""
        
        insights = []
        
        # SQL insights
        sql_analysis = data_analysis.get('sql_analysis')
        if sql_analysis and not sql_analysis.get('empty'):
            shape = sql_analysis.get('shape', [0, 0])
            quality_score = sql_analysis.get('data_quality_score', 0)
            insights.append(f"SQL Data: {shape[0]} records, {shape[1]} columns, {quality_score}% complete")
            
            patterns = sql_analysis.get('patterns', [])
            if patterns:
                insights.append(f"Patterns: {'; '.join(patterns[:3])}")
        
        # API insights
        api_analysis = data_analysis.get('api_analysis')
        if api_analysis and not api_analysis.get('error'):
            shape = api_analysis.get('shape', [0, 0])
            insights.append(f"API Data: {shape[0]} records extracted from execution output")
        
        # Combined insights
        combined = data_analysis.get('combined_analysis', {})
        total_records = combined.get('total_records', 0)
        data_sources = combined.get('data_sources', [])
        
        insights.append(f"Total Data: {total_records} records from {len(data_sources)} sources")
        
        return '\n'.join(f"- {insight}" for insight in insights)
    
    def _suggest_visualizations(self, data_analysis: Dict[str, Any], query: str) -> List[str]:
        """Suggest appropriate visualizations based on data analysis."""
        
        suggestions = []
        
        try:
            sql_analysis = data_analysis.get('sql_analysis', {})
            
            # Check for temporal data
            if any('date' in col.lower() or 'time' in col.lower() 
                   for col in sql_analysis.get('columns', [])):
                suggestions.append("Time series plot for temporal trends")
            
            # Check for categorical data
            categorical_distributions = [k for k in sql_analysis.keys() 
                                      if k.endswith('_distribution')]
            if categorical_distributions:
                suggestions.append("Bar charts for categorical distributions")
                suggestions.append("Pie charts for status/category breakdowns")
            
            # Check for user-related queries
            if 'user' in query.lower():
                suggestions.append("User activity heatmap")
                suggestions.append("User status distribution chart")
            
            # Check for group-related queries
            if 'group' in query.lower():
                suggestions.append("Group membership network diagram")
                suggestions.append("Group size comparison chart")
            
            # Check for access/permission queries
            if any(term in query.lower() for term in ['access', 'permission', 'role']):
                suggestions.append("Access matrix visualization")
                suggestions.append("Permission hierarchy diagram")
            
        except Exception as e:
            logger.warning(f"Error generating visualization suggestions: {str(e)}")
        
        return suggestions if suggestions else ["Data table for detailed view"]
    
    def _parse_enhanced_response(self, response: str, data_analysis: Dict[str, Any], 
                               flow_id: str) -> EnhancedProcessingResponse:
        """Parse LLM response and enhance with pandas insights."""
        
        try:
            logger.debug(f"[{flow_id}] Raw LLM3 response: {response[:500]}...")
            
            # Extract JSON from response
            cleaned_response = self._extract_json_from_response(response)
            logger.debug(f"[{flow_id}] Cleaned response: {cleaned_response[:500]}...")
            
            data = json.loads(cleaned_response)
            
            # ENHANCED: Handle multiple LLM3 response formats
            if "display_type" in data and "content" in data:
                # Standard expected format
                display_type = data["display_type"]
                content = data["content"]
                metadata = data.get("metadata", {})
            elif "user_query" in data and "results" in data:
                # Alternative format from LLM3 - convert to expected format
                logger.info(f"[{flow_id}] Converting alternative LLM3 format to expected format")
                
                # Extract meaningful content from results
                results = data.get("results", {})
                
                # Determine display type based on data structure
                if isinstance(results, dict) and "users" in results:
                    users = results.get("users", [])
                    if len(users) > 5:
                        display_type = "table"
                        # Convert to table format
                        content = []
                        for user in users:
                            user_row = {
                                "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                                "email": user.get("email", ""),
                                "login": user.get("login", ""),
                                "status": user.get("status", ""),
                                "groups": ", ".join([g.get("group_name", "") for g in user.get("groups", [])]),
                                "applications": ", ".join([a.get("label", "") for a in user.get("applications", [])])
                            }
                            content.append(user_row)
                    else:
                        display_type = "markdown"
                        # Convert to markdown format
                        content = f"## Users Who Logged In (Last 7 Days)\n\n"
                        content += f"Found **{results.get('unique_users', 0)} user(s)** from **{results.get('total_sql_records', 0)} records**\n\n"
                        
                        for user in users:
                            content += f"### {user.get('first_name', '')} {user.get('last_name', '')}\n"
                            content += f"- **Email**: {user.get('email', '')}\n"
                            content += f"- **Status**: {user.get('status', '')}\n"
                            
                            groups = user.get('groups', [])
                            if groups:
                                group_names = [g.get('group_name', '') for g in groups]
                                content += f"- **Groups**: {', '.join(group_names)}\n"
                            else:
                                content += f"- **Groups**: No group memberships found\n"
                            
                            apps = user.get('applications', [])
                            if apps:
                                app_names = [a.get('label', '') for a in apps]
                                content += f"- **Applications**: {', '.join(app_names)}\n"
                            else:
                                content += f"- **Applications**: No application assignments found\n"
                            content += "\n"
                else:
                    # Generic fallback
                    display_type = "markdown"
                    content = f"## Query Results\n\n{json.dumps(results, indent=2)}"
                
                # Create metadata
                metadata = {
                    "execution_summary": f"Found {results.get('unique_users', 0)} users with {results.get('total_sql_records', 0)} total records",
                    "confidence_level": "High",
                    "data_sources": ["sql", "api"],
                    "total_records": results.get('total_sql_records', 0),
                    "processing_time": "< 30 seconds",
                    "converted_from_alternative_format": True
                }
            elif "response" in data and ("data_quality" in data or "confidence_levels" in data):
                # NEW: Response-based format (response + data_quality/confidence_levels)
                logger.info(f"[{flow_id}] Converting response-based format to expected format")
                
                response_data = data.get("response", {})
                data_quality = data.get("data_quality", {})
                confidence_levels = data.get("confidence_levels", {})
                
                # Extract key metrics
                total_users = response_data.get("total_unique_users", 0)
                total_records = response_data.get("total_assignment_records", 0)
                app_count = response_data.get("application_assignments_count", 0)
                group_count = response_data.get("group_assignments_count", 0)
                
                if total_users == 0:
                    # No users found case
                    display_type = "markdown"
                    content = "## Users Who Logged In (Last 7 Days)\n\n"
                    content += "**No users found** who logged in during the last 7 days.\n\n"
                    content += "### Analysis:\n"
                    content += f"- Total Assignment Records: {total_records}\n"
                    content += f"- Application Assignments: {app_count}\n"
                    content += f"- Group Assignments: {group_count}\n"
                    content += f"- SQL Status: {data_quality.get('sql_query_status', 'unknown')}\n"
                    content += f"- API Status: {data_quality.get('api_fetch_status', 'unknown')}\n\n"
                    content += "### Possible Issues:\n"
                    content += "- User ID extraction from API events failed\n"
                    content += "- Login events didn't contain valid user identifiers\n"
                    content += "- SQL query used hardcoded IDs instead of dynamic extraction\n"
                else:
                    # Users found case
                    display_type = "markdown"
                    content = f"## Users Who Logged In (Last 7 Days)\n\n"
                    content += f"Found **{total_users} user(s)** with **{total_records} total assignment records**\n\n"
                    content += f"### Summary:\n"
                    content += f"- Average assignments per user: {response_data.get('average_assignments_per_user', 0)}\n"
                    content += f"- Application assignments: {app_count}\n"
                    content += f"- Group assignments: {group_count}\n\n"
                    content += f"### Data Quality:\n"
                    content += f"- Application data completeness: {data_quality.get('application_data_completeness', 'Unknown')}\n"
                    content += f"- Group data completeness: {data_quality.get('group_data_completeness', 'Unknown')}\n"
                
                # Create metadata
                metadata = {
                    "execution_summary": f"Found {total_users} users with {total_records} assignment records",
                    "confidence_level": confidence_levels.get("overall_confidence", "Medium"),
                    "data_sources": ["sql", "api"],
                    "total_records": total_records,
                    "sql_status": data_quality.get("sql_query_status", "unknown"),
                    "api_status": data_quality.get("api_fetch_status", "unknown"),
                    "processing_time": "< 40 seconds",
                    "converted_from_response_format": True
                }
            elif "users" in data and isinstance(data["users"], list):
                # NEW: Direct data format (users array at top level)
                logger.info(f"[{flow_id}] Converting direct data format to expected format")
                
                users = data.get("users", [])
                data_quality = data.get("data_quality", {})
                confidence_levels = data.get("confidence_levels", {})
                
                if len(users) == 0:
                    # No users found case
                    display_type = "markdown"
                    content = "## Users Who Logged In (Last 7 Days)\n\n"
                    content += "**No users found** who logged in during the last 7 days.\n\n"
                    content += "### Analysis:\n"
                    content += f"- API Records Extracted: {data_quality.get('api_records_extracted', 0)}\n"
                    content += f"- SQL Records Returned: {data_quality.get('sql_records_returned', 0)}\n"
                    content += f"- Quality Assessment: {data_quality.get('quality_assessment', 'Unknown')}\n\n"
                    content += "### Possible Reasons:\n"
                    content += "- No login activity in the last 7 days\n"
                    content += "- API filter configuration issues\n"
                    content += "- Missing user ID extraction from API events\n"
                elif len(users) > 5:
                    display_type = "table"
                    content = []
                    for user in users:
                        user_row = {
                            "name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                            "email": user.get("email", ""),
                            "login": user.get("login", ""),
                            "status": user.get("status", ""),
                            "groups": ", ".join([g.get("group_name", "") for g in user.get("groups", [])]),
                            "applications": ", ".join([a.get("label", "") for a in user.get("applications", [])])
                        }
                        content.append(user_row)
                else:
                    display_type = "markdown"
                    content = f"## Users Who Logged In (Last 7 Days)\n\n"
                    content += f"Found **{len(users)} user(s)**\n\n"
                    
                    for user in users:
                        content += f"### {user.get('first_name', '')} {user.get('last_name', '')}\n"
                        content += f"- **Email**: {user.get('email', '')}\n"
                        content += f"- **Status**: {user.get('status', '')}\n"
                        
                        groups = user.get('groups', [])
                        if groups:
                            group_names = [g.get('group_name', '') for g in groups]
                            content += f"- **Groups**: {', '.join(group_names)}\n"
                        else:
                            content += f"- **Groups**: No group memberships found\n"
                        
                        apps = user.get('applications', [])
                        if apps:
                            app_names = [a.get('label', '') for a in apps]
                            content += f"- **Applications**: {', '.join(app_names)}\n"
                        else:
                            content += f"- **Applications**: No application assignments found\n"
                        content += "\n"
                
                # Create metadata from the additional fields
                metadata = {
                    "execution_summary": f"Found {len(users)} users with API and SQL data analysis",
                    "confidence_level": confidence_levels.get("overall_confidence_assessment", "Medium"),
                    "data_sources": ["sql", "api"],
                    "total_records": data_quality.get("sql_records_returned", 0),
                    "api_records": data_quality.get("api_records_extracted", 0),
                    "planning_confidence": confidence_levels.get("planning_confidence_percent", 0),
                    "processing_time": "< 30 seconds",
                    "converted_from_direct_format": True,
                    "quality_assessment": data_quality.get("quality_assessment", "")
                }
            else:
                logger.warning(f"[{flow_id}] Unrecognized response format - creating fallback")
                return self._create_fallback_response(response, data_analysis, flow_id)
            
            # Enhance metadata with pandas insights
            enhanced_metadata = metadata.copy()
            enhanced_metadata.update({
                'pandas_enhanced': True,
                'data_quality_score': self._extract_quality_score(data_analysis),
                'total_records_analyzed': self._extract_total_records(data_analysis),
                'data_sources': data_analysis.get('combined_analysis', {}).get('data_sources', []),
                'processing_timestamp': datetime.now().isoformat()
            })
            
            return EnhancedProcessingResponse(
                display_type=display_type,
                content=content,
                metadata=enhanced_metadata,
                data_insights=data_analysis,
                visualization_suggestions=[]  # Will be populated later
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"[{flow_id}] JSON decode error: {str(e)}")
            return self._create_fallback_response(response, data_analysis, flow_id)
        except Exception as e:
            logger.error(f"[{flow_id}] Error parsing enhanced response: {str(e)}")
            return self._create_fallback_response(response, data_analysis, flow_id)
    
    def _extract_json_from_response(self, response: str) -> str:
        """Extract JSON from response, handling markdown code blocks."""
        
        # Try to find JSON code block
        json_block = re.search(r'```(?:json)?\s*\n(.*?)\n```', response, re.DOTALL)
        if json_block:
            return json_block.group(1).strip()
        
        # Try to find JSON object
        json_object = re.search(r'(\{.*\})', response, re.DOTALL)
        if json_object:
            return json_object.group(1).strip()
        
        return response.strip()
    
    def _extract_quality_score(self, data_analysis: Dict[str, Any]) -> float:
        """Extract overall data quality score."""
        sql_analysis = data_analysis.get('sql_analysis', {})
        return sql_analysis.get('data_quality_score', 0.0)
    
    def _extract_total_records(self, data_analysis: Dict[str, Any]) -> int:
        """Extract total number of records analyzed."""
        combined = data_analysis.get('combined_analysis', {})
        return combined.get('total_records', 0)
    
    def _create_error_response(self, error_message: str) -> EnhancedProcessingResponse:
        """Create error response."""
        return EnhancedProcessingResponse(
            display_type="markdown",
            content=f"**Error processing results**: {error_message}",
            metadata={"error": error_message, "pandas_enhanced": False}
        )
    
    def _create_fallback_response(self, raw_response: str, data_analysis: Dict[str, Any], 
                                flow_id: str) -> EnhancedProcessingResponse:
        """Create fallback response when LLM3 doesn't return valid JSON."""
        
        logger.info(f"[{flow_id}] Creating fallback response from raw LLM output")
        
        # Extract meaningful content from the raw response
        content = raw_response.strip() if raw_response else "No response from LLM3"
        
        # Enhance with basic insights
        metadata = {
            'pandas_enhanced': True,
            'data_quality_score': self._extract_quality_score(data_analysis),
            'total_records_analyzed': self._extract_total_records(data_analysis),
            'data_sources': data_analysis.get('combined_analysis', {}).get('data_sources', []),
            'processing_timestamp': datetime.now().isoformat(),
            'fallback_reason': 'LLM3 did not return valid JSON format'
        }
        
        return EnhancedProcessingResponse(
            display_type="markdown",
            content=content,
            metadata=metadata,
            data_insights=data_analysis,
            visualization_suggestions=[]
        )


# Create a singleton instance
enhanced_results_processor = PandasEnhancedResultsProcessor()


# Pandas utility functions for advanced data processing
class PandasDataProcessor:
    """Utility class for advanced pandas operations on Okta data."""
    
    @staticmethod
    def analyze_user_activity(df: pd.DataFrame) -> Dict[str, Any]:
        """Analyze user activity patterns from log data."""
        
        if df.empty:
            return {"error": "No data to analyze"}
        
        analysis = {}
        
        try:
            # Convert timestamp columns to datetime
            timestamp_cols = [col for col in df.columns if 'time' in col.lower() or 'date' in col.lower()]
            for col in timestamp_cols:
                df[col] = pd.to_datetime(df[col], errors='coerce')
            
            # Activity volume by day
            if timestamp_cols:
                main_timestamp = timestamp_cols[0]
                df['date'] = df[main_timestamp].dt.date
                daily_activity = df.groupby('date').size()
                analysis['daily_activity'] = daily_activity.to_dict()
                analysis['peak_activity_day'] = daily_activity.idxmax()
                analysis['avg_daily_activity'] = daily_activity.mean()
            
            # User activity patterns
            if 'user_id' in df.columns or 'actor_id' in df.columns:
                user_col = 'user_id' if 'user_id' in df.columns else 'actor_id'
                user_activity = df[user_col].value_counts()
                analysis['top_active_users'] = user_activity.head(10).to_dict()
                analysis['total_unique_users'] = user_activity.nunique()
            
        except Exception as e:
            analysis['error'] = str(e)
        
        return analysis
    
    @staticmethod
    def analyze_group_membership(df: pd.DataFrame) -> Dict[str, Any]:
        """Analyze group membership patterns."""
        
        analysis = {}
        
        try:
            # Group size analysis
            if 'group_id' in df.columns:
                group_sizes = df['group_id'].value_counts()
                analysis['group_sizes'] = group_sizes.describe().to_dict()
                analysis['largest_groups'] = group_sizes.head(10).to_dict()
            
            # User group memberships
            if 'user_id' in df.columns and 'group_id' in df.columns:
                user_groups = df.groupby('user_id')['group_id'].count()
                analysis['user_group_counts'] = user_groups.describe().to_dict()
                analysis['users_with_most_groups'] = user_groups.nlargest(10).to_dict()
            
        except Exception as e:
            analysis['error'] = str(e)
        
        return analysis
    
    @staticmethod
    def generate_processing_code(data_sample: List[Dict], analysis_type: str) -> str:
        """Generate pandas processing code for large datasets."""
        
        if not data_sample:
            return "# No data sample provided"
        
        # Detect columns from sample
        sample_df = pd.DataFrame(data_sample)
        columns = list(sample_df.columns)
        
        code_template = f"""
import pandas as pd
import numpy as np
from datetime import datetime

# Load the complete dataset
df = pd.DataFrame(data)  # 'data' should be the complete dataset

print(f"Dataset shape: {{df.shape}}")
print(f"Columns: {{list(df.columns)}}")

# Data quality check
print("\\nData Quality Summary:")
print(f"Total records: {{len(df)}}")
print(f"Null values per column:")
print(df.isnull().sum())

# Convert datetime columns
datetime_cols = {[col for col in columns if 'time' in col.lower() or 'date' in col.lower()]}
for col in datetime_cols:
    if col in df.columns:
        df[col] = pd.to_datetime(df[col], errors='coerce')

# Analysis based on type: {analysis_type}
"""
        
        if analysis_type == "user_analysis":
            code_template += """
# User-specific analysis
if 'user_id' in df.columns or 'id' in df.columns:
    user_col = 'user_id' if 'user_id' in df.columns else 'id'
    
    # User activity summary
    user_counts = df[user_col].value_counts()
    print(f"\\nUser Activity Summary:")
    print(f"Total unique users: {user_counts.nunique()}")
    print(f"Average records per user: {user_counts.mean():.2f}")
    
    # Top active users
    print("\\nTop 10 Most Active Users:")
    print(user_counts.head(10))

# Status analysis if available
if 'status' in df.columns:
    status_dist = df['status'].value_counts()
    print(f"\\nStatus Distribution:")
    print(status_dist)
"""
        
        elif analysis_type == "group_analysis":
            code_template += """
# Group-specific analysis
if 'group_id' in df.columns:
    group_counts = df['group_id'].value_counts()
    print(f"\\nGroup Analysis:")
    print(f"Total unique groups: {group_counts.nunique()}")
    print(f"Average members per group: {group_counts.mean():.2f}")
    
    # Largest groups
    print("\\nTop 10 Largest Groups:")
    print(group_counts.head(10))
"""
        
        elif analysis_type == "application_analysis":
            code_template += """
# Application-specific analysis
if 'app_id' in df.columns or 'application_id' in df.columns:
    app_col = 'app_id' if 'app_id' in df.columns else 'application_id'
    
    app_usage = df[app_col].value_counts()
    print(f"\\nApplication Usage Summary:")
    print(f"Total unique applications: {app_usage.nunique()}")
    print(f"Average usage per app: {app_usage.mean():.2f}")
    
    # Most used applications
    print("\\nTop 10 Most Used Applications:")
    print(app_usage.head(10))
"""
        
        code_template += """
# Export results
results_summary = {
    'total_records': len(df),
    'unique_columns': list(df.columns),
    'data_types': df.dtypes.to_dict(),
    'null_counts': df.isnull().sum().to_dict(),
    'analysis_timestamp': datetime.now().isoformat()
}

print(f"\\nAnalysis complete. Summary: {results_summary}")
"""
        
        return code_template
