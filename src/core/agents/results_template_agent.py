"""
Results Template Agent - Template-based Results Formatting with PydanticAI

This agent replaces the code-generation approach with a template-based system.
Instead of generating Python code, it selects and configures predefined templates
for common data processing patterns.

Templates Available:
1. SIMPLE_TABLE: Direct field mapping from one dataset
2. USER_LOOKUP: Join user data with enrichment data (most common)
3. AGGREGATION: Group by entity and aggregate fields
4. HIERARCHY: Parent-child relationships
5. LIST_CONSOLIDATION: Merge multiple list fields

Model Configuration:
- Uses REASONING model for data analysis and template selection
"""

import os
import sys
import json
import logging
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent

# Add src path for importing utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from src.utils.logging import get_logger, get_default_log_dir

# Setup centralized logging
logger = get_logger("okta_ai_agent", log_dir=get_default_log_dir())

# Use the model picker approach for consistent model configuration
try:
    from src.core.models.model_picker import ModelConfig, ModelType
    reasoning_model = ModelConfig.get_model(ModelType.REASONING)
except ImportError:
    # Fallback to simple model configuration
    reasoning_model = os.getenv('LLM_MODEL', 'openai:gpt-4o')

class FieldMapping(BaseModel):
    """Field mapping configuration"""
    output_field: str = Field(..., description="Name of field in output")
    source_dataset: str = Field(..., description="Dataset key (e.g., '1_api', '2_sql')")
    source_field: str = Field(..., description="Field name in source dataset")
    field_type: str = Field("string", description="Field type: string, list, number")
    default_value: str = Field("", description="Default value if field missing")

class ResultsTemplate(BaseModel):
    """Template configuration for results processing"""
    template_name: str = Field(..., description="Template identifier")
    display_type: str = Field("table", description="Output display type")
    primary_dataset: str = Field(..., description="Main dataset key (e.g., '1_api')")
    secondary_dataset: Optional[str] = Field(None, description="Secondary dataset for lookups")
    join_field: Optional[str] = Field(None, description="Field to join datasets on")
    field_mappings: List[FieldMapping] = Field(..., description="Output field mappings")
    headers: List[Dict[str, Any]] = Field(..., description="Table headers configuration")
    explanation: str = Field(..., description="What this template accomplishes")

def load_template_system_prompt() -> str:
    """Load template system prompt from external file"""
    try:
        prompt_file = os.path.join(os.path.dirname(__file__), 'prompts', 'results_formatter_sample_data_template_prompt.txt')
        with open(prompt_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"Template system prompt file not found: {prompt_file}")
        # Return inline fallback prompt
        return """You are a Results Template Agent that analyzes data structures and selects the appropriate template configuration for formatting results.

Analyze the provided data structure and generate a ResultsTemplate configuration that will properly format the data for display.

Available Templates:
1. SIMPLE_TABLE: Direct field mapping from one dataset
2. USER_LOOKUP: Join user data with enrichment data (most common pattern)
3. AGGREGATION: Group by entity and aggregate fields
4. HIERARCHY: Parent-child relationships
5. LIST_CONSOLIDATION: Merge multiple list fields

Always respond with a valid ResultsTemplate JSON object."""

class ResultsTemplateAgent:
    """Template-based results formatting agent"""
    
    def __init__(self):
        self.system_prompt = load_template_system_prompt()
        logger.info("Results Template Agent initialized")

    def _get_available_templates(self) -> Dict[str, str]:
        """Get descriptions of available templates"""
        return {
            "SIMPLE_TABLE": "Direct field mapping from single dataset - use when you have one dataset and need to display fields directly",
            "USER_LOOKUP": "Join pattern with user lookup - use when you have user IDs in one dataset and need to enrich with user details from another",
            "AGGREGATION": "Group by entity and aggregate - use when you need to group records by user/entity and aggregate list fields",
            "HIERARCHY": "Parent-child relationships - use for nested data like users->groups->applications",
            "LIST_CONSOLIDATION": "Merge multiple list fields - use when you have multiple list fields that need to be combined or deduplicated"
        }

    async def generate_template(self, query: str, data_structure: Dict[str, Any], 
                              original_plan: str, correlation_id: str) -> ResultsTemplate:
        """
        Generate template configuration based on data structure analysis
        
        Args:
            query: Original user query
            data_structure: Structure of available data
            original_plan: Original execution plan context
            correlation_id: Correlation ID for logging
            
        Returns:
            ResultsTemplate configuration
        """
        try:
            logger.info(f"[{correlation_id}] Template Agent: Starting template generation")
            
            # Create the template selection agent
            template_agent = Agent(
                reasoning_model,
                system_prompt=self.system_prompt,
                result_type=ResultsTemplate,
                retries=2
            )
            
            # Prepare context for template selection
            available_templates = self._get_available_templates()
            
            prompt_context = f"""
Query: {query}

Data Structure Analysis:
{json.dumps(data_structure, indent=2)}

Available Templates:
{json.dumps(available_templates, indent=2)}

Original Plan Context:
{original_plan}

Select the most appropriate template and configure the field mappings to properly format this data for display.
Consider the user's intent from the query and the structure of the available data.
"""
            
            logger.debug(f"[{correlation_id}] Template selection context: {len(prompt_context)} characters")
            
            # Generate template configuration
            result = await template_agent.run(prompt_context)
            template_config = result.data
            
            logger.info(f"[{correlation_id}] Template generation completed: {template_config.template_name}")
            logger.debug(f"[{correlation_id}] Template config: {len(template_config.field_mappings)} field mappings")
            
            return template_config
            
        except Exception as e:
            logger.error(f"[{correlation_id}] Template generation failed: {e}")
            # Return fallback simple template
            return self._create_fallback_template(data_structure)
    
    def _create_fallback_template(self, data_structure: Dict[str, Any]) -> ResultsTemplate:
        """Create a simple fallback template when generation fails"""
        logger.warning("Creating fallback simple table template")
        
        # Find the first dataset with data
        primary_dataset = None
        sample_record = None
        
        for dataset_key, dataset_value in data_structure.items():
            if isinstance(dataset_value, list) and len(dataset_value) > 0:
                primary_dataset = dataset_key
                sample_record = dataset_value[0]
                break
        
        if not primary_dataset or not sample_record:
            # Ultimate fallback
            return ResultsTemplate(
                template_name="SIMPLE_TABLE",
                primary_dataset="1_api",
                field_mappings=[
                    FieldMapping(
                        output_field="data",
                        source_dataset="1_api", 
                        source_field="*",
                        field_type="string"
                    )
                ],
                headers=[{"value": "data", "text": "Data", "sortable": True}],
                explanation="Fallback template for unknown data structure"
            )
        
        # Create field mappings from sample record
        field_mappings = []
        headers = []
        
        for field_name in sample_record.keys():
            field_mappings.append(FieldMapping(
                output_field=field_name,
                source_dataset=primary_dataset,
                source_field=field_name,
                field_type="string"
            ))
            headers.append({
                "value": field_name,
                "text": field_name.replace('_', ' ').title(),
                "sortable": True
            })
        
        return ResultsTemplate(
            template_name="SIMPLE_TABLE",
            primary_dataset=primary_dataset,
            field_mappings=field_mappings,
            headers=headers,
            explanation=f"Simple table template for {primary_dataset} data"
        )

# Template execution engine
class TemplateExecutor:
    """Executes template configurations to generate formatted results"""
    
    @staticmethod
    def execute_template(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a template configuration against data
        
        Args:
            template: Template configuration
            data: Full results data
            
        Returns:
            Formatted results ready for display
        """
        try:
            if template.template_name == "SIMPLE_TABLE":
                return TemplateExecutor._execute_simple_table(template, data)
            elif template.template_name == "USER_LOOKUP":
                return TemplateExecutor._execute_user_lookup(template, data)
            elif template.template_name == "AGGREGATION":
                return TemplateExecutor._execute_aggregation(template, data)
            elif template.template_name == "HIERARCHY":
                return TemplateExecutor._execute_hierarchy(template, data)
            elif template.template_name == "LIST_CONSOLIDATION":
                return TemplateExecutor._execute_list_consolidation(template, data)
            else:
                logger.warning(f"Unknown template: {template.template_name}, falling back to simple table")
                return TemplateExecutor._execute_simple_table(template, data)
                
        except Exception as e:
            logger.error(f"Template execution failed: {e}")
            return {
                "display_type": "error",
                "content": {"text": f"Template execution failed: {e}"},
                "metadata": {"error": str(e)}
            }
    
    @staticmethod
    def _execute_simple_table(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute simple table template"""
        primary_data = data.get(template.primary_dataset, [])
        if not isinstance(primary_data, list):
            primary_data = [primary_data] if primary_data else []
        
        result_records = []
        for record in primary_data:
            output_record = {}
            for mapping in template.field_mappings:
                if mapping.source_field == "*":
                    # Special case: include all fields
                    output_record.update(record)
                else:
                    value = record.get(mapping.source_field, mapping.default_value)
                    output_record[mapping.output_field] = value
            result_records.append(output_record)
        
        return {
            "display_type": template.display_type,
            "content": result_records,
            "metadata": {
                "template_used": template.template_name,
                "headers": template.headers,
                "total_records": len(result_records),
                "explanation": template.explanation
            }
        }
    
    @staticmethod
    def _execute_user_lookup(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute user lookup template (most common pattern)"""
        primary_data = data.get(template.primary_dataset, [])
        secondary_data = data.get(template.secondary_dataset, []) if template.secondary_dataset else []
        
        # Ensure data is in list format
        if not isinstance(primary_data, list):
            primary_data = [primary_data] if primary_data else []
        if not isinstance(secondary_data, list):
            secondary_data = [secondary_data] if secondary_data else []
        
        # Build lookup map
        lookup_map = {}
        join_field = template.join_field or "okta_id"
        
        for record in secondary_data:
            key = record.get(join_field)
            if key:
                lookup_map[key] = record
        
        # Process results
        result_records = []
        for primary_record in primary_data:
            # Handle case where primary data might be just IDs
            if isinstance(primary_record, str):
                lookup_key = primary_record
                primary_record = {join_field: primary_record}
            else:
                lookup_key = primary_record.get(join_field)
            
            # Get lookup data
            lookup_record = lookup_map.get(lookup_key, {})
            
            # Build output record
            output_record = {}
            for mapping in template.field_mappings:
                if mapping.source_dataset == template.primary_dataset:
                    value = primary_record.get(mapping.source_field, mapping.default_value)
                else:
                    value = lookup_record.get(mapping.source_field, mapping.default_value)
                
                # Handle list fields
                if mapping.field_type == "list" and isinstance(value, str):
                    value = [item.strip() for item in value.split(',') if item.strip()]
                elif mapping.field_type == "list" and not isinstance(value, list):
                    value = [str(value)] if value else []
                
                output_record[mapping.output_field] = value
            
            result_records.append(output_record)
        
        return {
            "display_type": template.display_type,
            "content": result_records,
            "metadata": {
                "template_used": template.template_name,
                "headers": template.headers,
                "total_records": len(result_records),
                "primary_dataset": template.primary_dataset,
                "secondary_dataset": template.secondary_dataset,
                "explanation": template.explanation
            }
        }
    
    @staticmethod
    def _execute_aggregation(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute aggregation template"""
        # Implementation for aggregation pattern
        # For now, fall back to simple table
        return TemplateExecutor._execute_simple_table(template, data)
    
    @staticmethod
    def _execute_hierarchy(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute hierarchy template"""
        # Implementation for hierarchy pattern
        # For now, fall back to simple table
        return TemplateExecutor._execute_simple_table(template, data)
    
    @staticmethod
    def _execute_list_consolidation(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute list consolidation template"""
        # Implementation for list consolidation pattern
        # For now, fall back to simple table
        return TemplateExecutor._execute_simple_table(template, data)

# Create global instances
template_agent = ResultsTemplateAgent()
template_executor = TemplateExecutor()

# Convenience functions
async def generate_results_template(query: str, data_structure: Dict[str, Any], 
                                  original_plan: str, correlation_id: str) -> ResultsTemplate:
    """Generate template configuration"""
    return await template_agent.generate_template(query, data_structure, original_plan, correlation_id)

def execute_results_template(template: ResultsTemplate, data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute template configuration"""
    return template_executor.execute_template(template, data)

def execute_results_template_from_dict(template_dict: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Execute template configuration from dictionary (for processing code execution)"""
    template = ResultsTemplate(**template_dict)
    return template_executor.execute_template(template, data)
