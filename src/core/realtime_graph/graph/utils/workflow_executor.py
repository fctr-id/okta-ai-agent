import asyncio
import re
from typing import Dict, List, Any, Optional, Union
import logging

from src.core.realtime_graph.graph.state import OktaState
from src.core.realtime_graph.graph.deps import OktaDeps
from src.core.realtime_graph.graph.utils.state_resolver import StateReferenceResolver, StateReferenceError

class WorkflowExecutor:
    """
    Executes Okta operations with state management and parameter substitution.
    
    This is a simplified alternative to the full graph-based approach,
    providing core functionality with less complexity.
    """
    
    def __init__(self, okta_client, logger=None, query_id="unknown", okta_deps: Optional[OktaDeps] = None):
        """
        Initialize workflow executor.
        
        Args:
            okta_client: Okta API client instance
            logger: Optional logger instance
            query_id: Query identifier for logging
            okta_deps: Optional OktaDeps instance containing dependencies
        """
        self.okta_client = okta_client
        self.logger = logger or logging.getLogger("okta_workflow")
        self.query_id = query_id
        self.state = OktaState()
        self.okta_deps = okta_deps
    
    async def resolve_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve any state references in parameters.
        
        Args:
            params: Dictionary of parameters that may contain state references
            
        Returns:
            Dictionary of resolved parameters
        """
        resolved_params = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("state."):
                try:
                    resolved_value = StateReferenceResolver.resolve_reference(
                        value, self.state, self.logger, self.query_id
                    )
                    resolved_params[key] = resolved_value
                    self.logger.info(f"[{self.query_id}] Resolved '{value}' to value of type {type(resolved_value).__name__}")
                except StateReferenceError as e:
                    self.logger.error(f"[{self.query_id}] Parameter error: {str(e)}")
                    raise
            else:
                resolved_params[key] = value
                
        return resolved_params
    
    def _extract_item_value(self, template: str, item: Any) -> Any:
        """
        Extract a value from an item using a template string.
        
        Handles formats like:
        - item['id']
        - item["id"]
        - item.id
        
        Args:
            template: Template string with item reference
            item: Item from which to extract the value
            
        Returns:
            Extracted value or None if extraction fails
        """
        if not isinstance(template, str):
            return template
            
        # Handle item['key'] or item["key"]
        bracket_match = re.search(r"item\[([\'\"])(.*?)\1\]", template)
        if bracket_match:
            key = bracket_match.group(2)
            if isinstance(item, dict) and key in item:
                return item[key]
            self.logger.warning(f"[{self.query_id}] Item does not have key '{key}'")
            return None
            
        # Handle item.key
        dot_match = re.search(r"item\.(\w+)", template)
        if dot_match:
            key = dot_match.group(1)
            if hasattr(item, key):
                return getattr(item, key)
            elif isinstance(item, dict) and key in item:
                return item[key]
            self.logger.warning(f"[{self.query_id}] Item does not have attribute '{key}'")
            return None
            
        return template
    
    async def execute_step(self, step_type: str, **params):
        """
        Execute a single operation step.
        
        Args:
            step_type: Type of operation to perform
            **params: Parameters for the operation
            
        Returns:
            Result of the operation
        """
        # Resolve any state references in parameters
        resolved_params = await self.resolve_params(params)
        
        # Execute the appropriate operation based on step type
        if step_type == "search_users":
            query = resolved_params.get("search_query")
            self.logger.info(f"[{self.query_id}] Searching users with query: {query}")
            
            try:
                if not query:
                    self.logger.error(f"[{self.query_id}] No query provided for search_users")
                    raise ValueError("No query provided for user search")
                
                self.logger.info(f"[{self.query_id}] Using filter query: {query}")
                users, resp, err = await self.okta_client.list_users(query_params={"filter": query})
                
                if err:
                    self.logger.error(f"[{self.query_id}] Okta API error: {err}")
                    raise RuntimeError(f"Failed to search users: {err}")
                    
                self.logger.info(f"[{self.query_id}] Found {len(users)} users matching query")
                self.state.users_list = users
                
                if users and len(users) > 0:
                    first_user = users[0]
                    self.logger.info(f"[{self.query_id}] User type: {type(first_user).__name__}")
                    
                    # If it's a dictionary, log its keys
                    if isinstance(first_user, dict):
                        self.logger.info(f"[{self.query_id}] First user keys: {list(first_user.keys())}")
                    else:
                        # If it's an object, try to log its attributes
                        self.logger.info(f"[{self.query_id}] First user dir: {[a for a in dir(first_user) if not a.startswith('_') and not callable(getattr(first_user, a))][0:10]}")
                        # Log if it has an id attribute
                        self.logger.info(f"[{self.query_id}] Has id attribute: {hasattr(first_user, 'id')}")
                        if hasattr(first_user, 'id'):
                            self.logger.info(f"[{self.query_id}] id value: {first_user.id}")

                self.state.users_list = users
                
                return users
            except Exception as e:
                self.logger.exception(f"[{self.query_id}] Exception in search_users: {str(e)}")
                raise
            
        elif step_type == "get_user_details":
            user_id = resolved_params.get("user_id")
            self.logger.info(f"[{self.query_id}] Getting user details for: {user_id}")
            
            try:
                user, resp, err = await self.okta_client.get_user(user_id)
                
                if err:
                    raise RuntimeError(f"Failed to get user details: {err}")
                    
                # Add some debug logging to see what's being returned
                self.logger.info(f"[{self.query_id}] Retrieved user details for {user_id}")
                
                return user
            except Exception as e:
                self.logger.exception(f"[{self.query_id}] Exception in get_user_details: {str(e)}")
                raise
            
        elif step_type == "get_user_factors":
            user_id = resolved_params.get("user_id")
            self.logger.info(f"[{self.query_id}] Getting factors for user: {user_id}")
            
            try:
                factors, resp, err = await self.okta_client.list_factors(user_id)
                
                if err:
                    raise RuntimeError(f"Failed to list factors: {err}")
                    
                return factors
            except Exception as e:
                self.logger.exception(f"[{self.query_id}] Exception in get_user_factors: {str(e)}")
                raise
            
        elif step_type == "get_user_groups":
            user_id = resolved_params.get("user_id")
            self.logger.info(f"[{self.query_id}] Getting groups for user: {user_id}")
            
            try:
                groups, resp, err = await self.okta_client.list_user_groups(user_id)
                
                if err:
                    raise RuntimeError(f"Failed to list user groups: {err}")
                    
                return groups
            except Exception as e:
                self.logger.exception(f"[{self.query_id}] Exception in get_user_groups: {str(e)}")
                raise
            
        elif step_type == "get_group_members":
            group_id = resolved_params.get("group_id")
            self.logger.info(f"[{self.query_id}] Getting members for group: {group_id}")
            
            try:
                members, resp, err = await self.okta_client.list_group_members(group_id)
                
                if err:
                    raise RuntimeError(f"Failed to list group members: {err}")
                    
                return members
            except Exception as e:
                self.logger.exception(f"[{self.query_id}] Exception in get_group_members: {str(e)}")
                raise
            
        # Add this in the execute_step method, replacing the existing for_each section:
        
        elif step_type == "for_each":
            # Extract parameters exactly as defined in the prompt
            items_ref = resolved_params.get("items")
            operation = resolved_params.get("operation")
            params = {}
            output_var = resolved_params.get("output", "operation_results")
            
            # Handle operation structure according to prompt format
            if isinstance(operation, dict):
                if "type" in operation:
                    op_type = operation["type"]
                    # If params are in the operation dict, use those
                    if "params" in operation:
                        params = operation["params"]
                else:
                    op_type = operation
            else:
                op_type = operation
            
            self.logger.info(f"[{self.query_id}] ForEach with operation={operation}, output={output_var}")
            
            # Get the collection from state
            items = None
            if isinstance(items_ref, str):
                attr_name = items_ref.replace("state.", "") if items_ref.startswith("state.") else items_ref
                if hasattr(self.state, attr_name):
                    items = getattr(self.state, attr_name)
                else:
                    raise ValueError(f"Collection '{attr_name}' not found on state")
            elif isinstance(items_ref, list):
                items = items_ref
            else:
                raise ValueError("'items' must be a list or string reference")
            
            # Process items with the operation
            results = []
            for i, item in enumerate(items):
                # Process parameters for this item
                item_params = {}
                for key, value in params.items():
                    if isinstance(value, str) and "item." in value:
                        # Handle item.attribute syntax
                        attr = value.replace("item.", "")
                        if isinstance(item, dict) and attr in item:
                            item_params[key] = item[attr]
                        elif hasattr(item, attr):
                            item_params[key] = getattr(item, attr)
                        else:
                            self.logger.error(f"[{self.query_id}] Attribute '{attr}' not found in item")
                            item_params[key] = None
                    else:
                        item_params[key] = value
                
                # Execute operation for this item
                self.logger.info(f"[{self.query_id}] Processing item {i+1}/{len(items)} with params: {item_params}")
                result = await self.execute_step(op_type.lower(), **item_params)
                results.append(result)
            
            # Store results in state using the specified output variable
            setattr(self.state, output_var, results)
            self.logger.info(f"[{self.query_id}] Stored {len(results)} results in state.{output_var}")
            
            return results
        
        elif step_type == "join_results":
            results_ref = resolved_params.get("results")
            join_type = resolved_params.get("join_type", "merge")
            key = resolved_params.get("key")
            
            self.logger.info(f"[{self.query_id}] Joining results with type={join_type}, key={key}")
            
            # Get results from state
            results = None
            if isinstance(results_ref, str):
                attr_name = results_ref.replace("state.", "") if results_ref.startswith("state.") else results_ref
                if hasattr(self.state, attr_name):
                    results = getattr(self.state, attr_name)
                else:
                    raise ValueError(f"Results collection '{attr_name}' not found")
            elif isinstance(results_ref, list):
                results = results_ref
            else:
                raise ValueError("'results' must be a list or string reference")
            
            if not isinstance(results, list):
                raise ValueError(f"Results must be a list, got {type(results).__name__}")
            
            # Process based on join type
            if join_type.lower() == "extract":
                # Extract a specific field from each item
                joined_results = []
                for item in results:
                    if key:
                        # Handle nested keys like "profile.email"
                        value = item
                        for part in key.split('.'):
                            if isinstance(value, dict) and part in value:
                                value = value[part]
                            elif hasattr(value, part):
                                value = getattr(value, part)
                            else:
                                self.logger.error(f"[{self.query_id}] Key '{part}' not found in {type(value).__name__}")
                                value = None
                                break
                        joined_results.append(value)
                    else:
                        joined_results.append(item)
                
                self.logger.info(f"[{self.query_id}] Extracted {len(joined_results)} values")
                return joined_results
            
            elif join_type.lower() == "merge":
                # Merge all results into a single list or object
                self.logger.info(f"[{self.query_id}] Merged {len(results)} items")
                return results
            
            else:
                self.logger.error(f"[{self.query_id}] Unsupported join type: {join_type}")
                raise ValueError(f"Unsupported join type: {join_type}")        
    
    async def execute_workflow(self, steps: List[Dict[str, Any]]):
        """
        Execute a sequence of steps as a workflow.
        
        Args:
            steps: List of operation definitions
            
        Returns:
            Dictionary with execution results and status
        """
        results = []
        
        for i, step in enumerate(steps):
            step_type = step.get("type")
            params = step.get("params", {})
            
            self.logger.info(f"[{self.query_id}] Executing step {i+1}/{len(steps)}: {step_type}")
            
            try:
                result = await self.execute_step(step_type, **params)
                results.append({"step": step_type, "result": result})
                
                # Store to state.result for convenient access
                self.state.result = result
                
            except Exception as e:
                self.logger.error(f"[{self.query_id}] Step failed: {str(e)}")
                self.state.errors.append(str(e))
                return {
                    "results": results, 
                    "completed": False, 
                    "errors": self.state.errors,
                    "final_result": None
                }
        
        return {
            "results": results, 
            "completed": True, 
            "errors": self.state.errors if self.state.errors else None,
            "final_result": self.state.result
        }
        
    def safe_store_results(self, result_var, results, operation_type=None):
        """Safely store results in state with proper validation."""
        
        # If no result variable specified, try to infer a sensible one
        if result_var is None and operation_type:
            # E.g., "GetUserDetails" -> "user_details_list"
            base_name = operation_type.lower().replace("get_", "").replace("get", "")
            result_var = f"{base_name}_list"
        elif result_var is None:
            result_var = "results_list"
        
        # If it's a state reference, extract just the attribute name
        if isinstance(result_var, str) and result_var.startswith("state."):
            result_var = result_var[6:]  # Remove "state." prefix
        
        # Validate attribute name (alphanumeric + underscores only)
        if not re.match(r'^[a-zA-Z0-9_]+$', result_var):
            self.logger.error(f"[{self.query_id}] Invalid attribute name '{result_var}', using safe default")
            result_var = "safe_results"
        
        # Don't overwrite critical attributes
        reserved_attrs = ['execute_workflow', 'execute_step', 'resolve_params', 'client', 'okta_deps']
        if result_var in reserved_attrs:
            self.logger.error(f"[{self.query_id}] Cannot overwrite reserved attribute '{result_var}'")
            result_var = f"safe_{result_var}"
        
        # Store the results with clear logging
        setattr(self.state, result_var, results)
        self.logger.error(f"[{self.query_id}] Stored {len(results)} results in state.{result_var}")
        
        return result_var 
    
           