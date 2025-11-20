"""
Polars Pattern Library - Pre-validated Polars operations for safe execution

This module contains pre-tested, version-safe Polars patterns that the LLM can select
and parameterize, rather than generating arbitrary Polars code.
"""

import polars as pl
import json
from typing import Dict, Any, List, Optional, Union
import logging

logger = logging.getLogger("okta_ai_agent")


class PolarsPatternsLibrary:
    """Library of pre-validated Polars processing patterns"""
    
    @staticmethod
    def select_columns(df: pl.DataFrame, columns: List[str], aliases: Optional[Dict[str, str]] = None) -> pl.DataFrame:
        """Select specific columns with optional aliases"""
        if aliases:
            select_expr = []
            for col in columns:
                if col in aliases:
                    select_expr.append(pl.col(col).alias(aliases[col]))
                else:
                    select_expr.append(pl.col(col))
            return df.select(select_expr)
        else:
            return df.select(columns)
    
    @staticmethod
    def left_join(df1: pl.DataFrame, df2: pl.DataFrame, left_key: str, right_key: str) -> pl.DataFrame:
        """Perform left join between two DataFrames"""
        return df1.join(df2, left_on=left_key, right_on=right_key, how="left")
    
    @staticmethod
    def split_comma_list(df: pl.DataFrame, field: str, alias: str) -> pl.DataFrame:
        """Split comma-separated string into list"""
        return df.with_columns([pl.col(field).str.split(",").alias(alias)])
    
    @staticmethod
    def group_and_aggregate(df: pl.DataFrame, group_field: str, agg_fields: List[Dict[str, str]]) -> pl.DataFrame:
        """Group by field and aggregate specified fields"""
        agg_expressions = []
        for agg_spec in agg_fields:
            field = agg_spec["field"]
            operation = agg_spec["operation"]  # first, count, list, etc.
            alias = agg_spec.get("alias", f"{field}_{operation}")
            
            if operation == "first":
                agg_expressions.append(pl.col(field).first().alias(alias))
            elif operation == "count":
                agg_expressions.append(pl.col(field).count().alias(alias))
            elif operation == "list":
                agg_expressions.append(pl.col(field).list().alias(alias))
            elif operation == "concat":
                agg_expressions.append(pl.col(field).str.concat(",").alias(alias))
        
        return df.group_by(group_field).agg(agg_expressions)
    
    @staticmethod
    def explode_array_column(df: pl.DataFrame, array_column: str) -> pl.DataFrame:
        """Explode array column into separate rows, maintaining other columns"""
        return df.explode(array_column)
    
    @staticmethod
    def extract_nested_field(df: pl.DataFrame, json_column: str, field_path: str, alias: str) -> pl.DataFrame:
        """Extract nested field from JSON column (e.g., 'expiresAt' from certificate objects)"""
        # Handle nested field extraction from struct/JSON column
        if "." in field_path:
            # For nested paths like "certificate.expiresAt"
            parts = field_path.split(".")
            expr = pl.col(json_column)
            for part in parts:
                expr = expr.struct.field(part)
            return df.with_columns([expr.alias(alias)])
        else:
            # Simple field extraction
            return df.with_columns([pl.col(json_column).struct.field(field_path).alias(alias)])
    
    @staticmethod
    def explode_and_extract(df: pl.DataFrame, array_column: str, extract_fields: List[Dict[str, str]]) -> pl.DataFrame:
        """Combined pattern: explode array and extract specific fields from each item"""
        # First explode the array column
        df_exploded = df.explode(array_column)
        
        # Then extract specified fields from the exploded items
        expressions = []
        for field_spec in extract_fields:
            field_name = field_spec["field"]
            alias = field_spec["alias"]
            expressions.append(pl.col(array_column).struct.field(field_name).alias(alias))
        
        return df_exploded.with_columns(expressions)
    
    @staticmethod
    def flatten_and_concat(df: pl.DataFrame, column_to_flatten: str, extract_field: str, new_column_name: str) -> pl.DataFrame:
        """Flatten a list of structs, extract a field, and concatenate into a string."""
        return df.with_columns(
            pl.col(column_to_flatten)
            .list.eval(pl.element().struct.field(extract_field))
            .list.join(", ")
            .alias(new_column_name)
        )

    @staticmethod
    def filter_by_condition(df: pl.DataFrame, conditions: List[Dict[str, Any]]) -> pl.DataFrame:
        """Filter DataFrame based on a list of conditions (AND logic)"""
        if not conditions:
            return df
            
        exprs = []
        for cond in conditions:
            # Validate condition structure
            if not isinstance(cond, dict):
                logger.warning(f"Invalid condition format: {cond}. Skipping.")
                continue
                
            col = cond.get("column")
            op = cond.get("operator") 
            val = cond.get("value")
            
            # Validate required fields
            if not col or not op:
                logger.warning(f"Missing column or operator in condition: {cond}. Skipping.")
                continue
                
            # Check if column exists in DataFrame
            if col not in df.columns:
                logger.warning(f"Column '{col}' not found in DataFrame. Available columns: {df.columns}. Skipping condition.")
                continue
            
            try:
                if op == "eq":
                    exprs.append(pl.col(col) == val)
                elif op == "neq":
                    exprs.append(pl.col(col) != val)
                elif op == "gt":
                    exprs.append(pl.col(col) > val)
                elif op == "lt":
                    exprs.append(pl.col(col) < val)
                elif op == "is_in":
                    exprs.append(pl.col(col).is_in(val))
                elif op == "contains":
                    if val is not None:
                        exprs.append(pl.col(col).str.contains(str(val)))
                else:
                    logger.warning(f"Unknown operator '{op}' in condition: {cond}. Skipping.")
                    continue
                    
            except Exception as e:
                logger.warning(f"Failed to create condition for {cond}: {e}. Skipping.")
                continue
        
        if not exprs:
            logger.info("No valid filter conditions found, returning original DataFrame")
            return df
        
        try:
            # Combine all conditions with AND logic
            final_expr = exprs[0]
            for i in range(1, len(exprs)):
                final_expr = final_expr & exprs[i]
                
            return df.filter(final_expr)
        except Exception as e:
            logger.error(f"Failed to apply filter conditions: {e}. Returning original DataFrame.")
            return df

    @staticmethod
    def sort_by_columns(df: pl.DataFrame, sort_specs: List[Dict[str, Any]]) -> pl.DataFrame:
        """Sort DataFrame by one or more columns"""
        by = [spec["column"] for spec in sort_specs]
        descending = [spec.get("descending", False) for spec in sort_specs]
        return df.sort(by=by, descending=descending)

    @staticmethod
    def cast_column_type(df: pl.DataFrame, casts: List[Dict[str, str]]) -> pl.DataFrame:
        """Cast columns to specified Polars types"""
        exprs = []
        for cast_spec in casts:
            col = cast_spec["column"]
            dtype_str = cast_spec["dtype"]
            
            # Map string to Polars dtype
            if dtype_str == "datetime":
                dtype = pl.Datetime
            elif dtype_str == "date":
                dtype = pl.Date
            elif dtype_str == "int":
                dtype = pl.Int64
            elif dtype_str == "float":
                dtype = pl.Float64
            else:
                dtype = pl.Utf8 # Default to string
            
            exprs.append(pl.col(col).cast(dtype, strict=False))
        
        return df.with_columns(exprs)

    @staticmethod
    def filter_not_null(df: pl.DataFrame, column: str) -> pl.DataFrame:
        """Filter out null values in specified column"""
        return df.filter(pl.col(column).is_not_null())
    
    @staticmethod
    def fill_null_values(df: pl.DataFrame, fill_value: str = "") -> pl.DataFrame:
        """Fill null values with specified value"""
        return df.fill_null(fill_value)
    
    @staticmethod
    def create_user_friendly_headers(df: pl.DataFrame, field_mappings: Dict[str, str]) -> List[Dict[str, Any]]:
        """Create Vuetify-compatible headers with user-friendly names"""
        headers = []
        for col in df.columns:
            display_name = field_mappings.get(col, col.replace("_", " ").title())
            header = {
                "value": col,
                "text": display_name,
                "sortable": True
            }
            # Make certain fields non-sortable
            if col in ["roles", "applications", "groups"] or col.endswith("_list"):
                header["sortable"] = False
            headers.append(header)
        return headers

    @staticmethod
    def smart_dataframe_selection(dataframes: Dict[str, pl.DataFrame], preference_order: List[str], 
                                required_fields: List[str] = None, fallback_to_largest: bool = True) -> pl.DataFrame:
        """Intelligently select the best dataframe based on preferences and field availability"""
        # First, try preference order with required fields
        if required_fields:
            for pref_key in preference_order:
                if pref_key in dataframes:
                    df = dataframes[pref_key]
                    # Check if all required fields are present
                    if all(field in df.columns for field in required_fields):
                        return df
        
        # Fallback: try preference order without field requirements
        for pref_key in preference_order:
            if pref_key in dataframes:
                return dataframes[pref_key]
        
        # Final fallback: largest dataframe or first available
        if fallback_to_largest and dataframes:
            return max(dataframes.values(), key=lambda df: df.height)
        
        # Return first available dataframe
        return list(dataframes.values())[0] if dataframes else None

    @staticmethod
    def flatten_nested_arrays(df: pl.DataFrame, array_fields: List[str], strategy: str = "first_item") -> pl.DataFrame:
        """
        Polars-based flattening of nested arrays - HIGH PERFORMANCE
        
        Args:
            df: Input DataFrame with nested array columns
            array_fields: List of column names containing arrays of objects
            strategy: "first_item" (take first from each array) or "explode" (create multiple rows)
        
        Returns:
            Flattened DataFrame with prefixed column names
        """
        result_df = df.clone()
        
        for array_field in array_fields:
            if array_field not in df.columns:
                continue
                
            if strategy == "first_item":
                # Strategy 1: Take first item from each array (most LLM-friendly)
                prefix = array_field.rstrip('s')  # role_assignments -> role_assignment
                
                # Extract first item and create flattened columns
                try:
                    # Get the first element of each array
                    first_items = result_df.select(
                        pl.col(array_field).list.first().alias(f"{prefix}_first")
                    )
                    
                    # If first item is a struct/object, extract its fields
                    if not first_items.is_empty():
                        sample_item = first_items.to_dicts()[0][f"{prefix}_first"]
                        if isinstance(sample_item, dict):
                            # Create expressions to extract each field from the first item
                            extract_exprs = []
                            for field_name in sample_item.keys():
                                extract_exprs.append(
                                    pl.col(array_field)
                                    .list.first()
                                    .struct.field(field_name)
                                    .alias(f"{prefix}_{field_name}")
                                )
                            
                            # Add count column
                            extract_exprs.append(
                                pl.col(array_field).list.len().alias(f"{array_field}_count")
                            )
                            
                            # Apply extractions
                            result_df = result_df.with_columns(extract_exprs)
                    
                    # Remove original array column
                    result_df = result_df.drop(array_field)
                    
                except Exception as e:
                    logger.warning(f"Failed to flatten array field {array_field}: {e}")
                    # Keep original column if flattening fails
                    continue
                    
            elif strategy == "explode":
                # Strategy 2: Explode arrays into multiple rows
                result_df = result_df.explode(array_field)
                
                # Extract fields from exploded objects
                try:
                    if not result_df.is_empty():
                        sample_item = result_df.to_dicts()[0][array_field]
                        if isinstance(sample_item, dict):
                            prefix = array_field.rstrip('s')
                            extract_exprs = []
                            for field_name in sample_item.keys():
                                extract_exprs.append(
                                    pl.col(array_field)
                                    .struct.field(field_name)
                                    .alias(f"{prefix}_{field_name}")
                                )
                            
                            result_df = result_df.with_columns(extract_exprs)
                            result_df = result_df.drop(array_field)
                            
                except Exception as e:
                    logger.warning(f"Failed to explode and extract {array_field}: {e}")
                    continue
        
        return result_df

    @staticmethod 
    def auto_detect_and_flatten(df: pl.DataFrame) -> pl.DataFrame:
        """
        Automatically detect array columns and flatten them using Polars
        
        This is the main method that should be used by the LLM patterns
        """
        if df.is_empty():
            return df
            
        # Detect array columns by sampling first row
        sample_row = df.to_dicts()[0] if df.height > 0 else {}
        array_fields = []
        
        for col_name, value in sample_row.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                array_fields.append(col_name)
        
        if not array_fields:
            return df
            
        logger.info(f"Auto-detected array fields for flattening: {array_fields}")
        return PolarsPatternsLibrary.flatten_nested_arrays(df, array_fields, "first_item")


class PolarsPatternEngine:
    """Engine that executes Polars patterns based on LLM instructions"""
    
    def __init__(self):
        self.patterns = PolarsPatternsLibrary()
    
    def execute_processing_plan(self, data: Dict[str, List[Dict]], plan: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a processing plan generated by LLM"""
        try:
            # Convert data to Polars DataFrames
            dataframes = {}
            for key, records in data.items():
                if records and len(records) > 0:
                    dataframes[key] = pl.DataFrame(records)
            
            if not dataframes:
                return self._create_empty_result("No data to process")
            
            # Execute the plan
            result_df = self._execute_plan_steps(dataframes, plan)
            
            if result_df is None or result_df.height == 0:
                return self._create_empty_result("No results after processing")
            
            # Convert to Vuetify format
            return self._format_for_vuetify(result_df, plan)
            
        except Exception as e:
            logger.error(f"PolarsPatternEngine execution failed for plan: {plan}", exc_info=True)
            return self._create_error_result(f"Pattern execution failed: {repr(e)}")
    
    def _execute_plan_steps(self, dataframes: Dict[str, pl.DataFrame], plan: Dict[str, Any]) -> Optional[pl.DataFrame]:
        """Execute the steps in the processing plan"""
        steps = plan.get("steps", [])
        entity_type = plan.get("entity_type", "unknown")
        
        if not steps:
            # No steps provided - let the LLM decide what to do with the data
            # This is the fallback that sends data to LLM for intelligent processing
            return self._simple_concatenation(dataframes)
        
        result_df = None
        
        for step in steps:
            pattern = step.get("pattern")
            params = step.get("params", {})
            
            # Add validation before executing patterns
            try:
                if pattern == "auto_detect_and_flatten":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    if df_key in dataframes:
                        result_df = self.patterns.auto_detect_and_flatten(dataframes[df_key])
                        logger.info(f"Auto-detected and flattened nested arrays in {df_key}")
                        
                elif pattern == "select_columns":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    if df_key in dataframes:
                        df = dataframes[df_key]
                        # Validate columns exist
                        requested_cols = params.get("columns", [])
                        available_cols = [col for col in requested_cols if col in df.columns]
                        if not available_cols:
                            logger.warning(f"No requested columns found in {df_key}, skipping select_columns")
                            continue
                        # Update params with only available columns
                        params["columns"] = available_cols
                        result_df = self.patterns.select_columns(
                            df,
                            available_cols,
                            params.get("aliases", {})
                        )
                
                elif pattern == "left_join":
                    left_key = params.get("left_df")
                    right_key = params.get("right_df")
                    left_field = params.get("left_field")
                    right_field = params.get("right_field")
                    
                    if (left_key in dataframes and right_key in dataframes and 
                        left_field in dataframes[left_key].columns and 
                        right_field in dataframes[right_key].columns):
                        result_df = self.patterns.left_join(
                            dataframes[left_key],
                            dataframes[right_key],
                            left_field,
                            right_field
                        )
                    else:
                        logger.warning(f"Join conditions not met for {left_key} and {right_key}")
                        # Fallback to primary dataframe
                        if left_key in dataframes:
                            result_df = dataframes[left_key]
                        else:
                            result_df = list(dataframes.values())[0]
                
                elif pattern == "group_and_aggregate":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    if df_key in dataframes:
                        result_df = self.patterns.group_and_aggregate(
                            dataframes[df_key],
                            params.get("group_field"),
                            params.get("aggregations", [])
                        )
                
                elif pattern == "user_enrichment":
                    # Special pattern for user data with applications/groups/roles
                    result_df = self._execute_user_enrichment(dataframes, params)
                
                elif pattern == "explode_array_column":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    array_column = params.get("array_column")
                    if df_key in dataframes and array_column in dataframes[df_key].columns:
                        result_df = self.patterns.explode_array_column(
                            dataframes[df_key],
                            array_column
                        )
                        # Update dataframes for next step
                        dataframes[df_key] = result_df
                
                elif pattern == "extract_nested_field":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    json_column = params.get("json_column")
                    if df_key in dataframes and json_column in dataframes[df_key].columns:
                        result_df = self.patterns.extract_nested_field(
                            dataframes[df_key],
                            json_column,
                            params.get("field_path"),
                            params.get("alias")
                        )
                        # Update dataframes for next step
                        dataframes[df_key] = result_df
                
                elif pattern == "explode_and_extract":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    
                    # Find the dataframe that actually contains the array column
                    array_column = params.get("array_column")
                    actual_df_key = df_key
                    
                    if df_key not in dataframes and array_column:
                        # Find dataframe that has the array column
                        for k, df in dataframes.items():
                            if array_column in df.columns:
                                actual_df_key = k
                                break
                    
                    if actual_df_key in dataframes and array_column in dataframes[actual_df_key].columns:
                        result_df = self.patterns.explode_and_extract(
                            dataframes[actual_df_key],
                            array_column,
                            params.get("extract_fields", [])
                        )
                        # Update dataframes for next step
                        dataframes[actual_df_key] = result_df
                
                elif pattern == "filter_by_condition":
                    df_key = params.get("dataframe", list(dataframes.keys())[0])
                    if result_df is not None:
                        result_df = self.patterns.filter_by_condition(
                            result_df,
                            params.get("conditions", [])
                        )
                    elif df_key in dataframes:
                        result_df = self.patterns.filter_by_condition(
                            dataframes[df_key],
                            params.get("conditions", [])
                        )
                
                elif pattern == "sort_by_columns":
                    if result_df is not None:
                        result_df = self.patterns.sort_by_columns(
                            result_df,
                            params.get("sort_specs", [])
                        )

                elif pattern == "cast_column_type":
                    if result_df is not None:
                        result_df = self.patterns.cast_column_type(
                            result_df,
                            params.get("casts", [])
                        )
                
                elif pattern == "smart_dataframe_selection":
                    result_df = self.patterns.smart_dataframe_selection(
                        dataframes,
                        params.get("preference_order", []),
                        params.get("required_fields", []),
                        params.get("fallback_to_largest", True)
                    )
                    
            except Exception as e:
                logger.error(f"Pattern execution failed for {pattern}: {e}")
                # Fallback to safest option
                if result_df is None:
                    result_df = list(dataframes.values())[0]
        
        return result_df
    
    def _execute_user_enrichment(self, dataframes: Dict[str, pl.DataFrame], params: Dict[str, Any]) -> pl.DataFrame:
        """Execute user enrichment pattern - combines user, app, group, role data"""
        # Find the main user data (usually from API-SQL step)
        user_df = None
        role_df = None
        
        for key, df in dataframes.items():
            if "api_sql" in key and "email" in df.columns:
                user_df = df
            elif "api" in key and "roles" in df.columns:
                role_df = df
        
        if user_df is None:
            return list(dataframes.values())[0]  # Fallback to first DataFrame
        
        # Join with role data if available
        if role_df is not None and "okta_id" in user_df.columns:
            # Create a roles summary
            role_df = role_df.with_columns([
                pl.when(pl.col("roles").list.len() > 0)
                .then(pl.col("roles").list.eval(pl.element().struct.field("label")).list.join(", "))
                .otherwise("")
                .alias("role_assignments")
            ])
            
            result_df = self.patterns.left_join(user_df, role_df, "okta_id", "user_id")
        else:
            result_df = user_df
        
        # Clean up the data
        result_df = self.patterns.fill_null_values(result_df)
        
        return result_df
    
    def _simple_concatenation(self, dataframes: Dict[str, pl.DataFrame]) -> pl.DataFrame:
        """Simple fallback: concatenate all DataFrames"""
        if len(dataframes) == 1:
            return list(dataframes.values())[0]
        
        # Try to find common columns and concatenate
        all_dfs = list(dataframes.values())
        common_cols = set(all_dfs[0].columns)
        
        for df in all_dfs[1:]:
            common_cols = common_cols.intersection(set(df.columns))
        
        if common_cols:
            # Select common columns and concatenate
            selected_dfs = [df.select(list(common_cols)) for df in all_dfs]
            return pl.concat(selected_dfs)
        else:
            # Return the largest DataFrame
            return max(all_dfs, key=lambda df: df.height)
    
    def _format_for_vuetify(self, df: pl.DataFrame, plan: Dict[str, Any]) -> Dict[str, Any]:
        """Format DataFrame for Vuetify data table"""
        # Convert to records
        content = df.to_dicts()
        
        # Create user-friendly headers
        field_mappings = plan.get("field_mappings", {})
        headers = self.patterns.create_user_friendly_headers(df, field_mappings)
        
        return {
            "display_type": "table",
            "content": content,
            "metadata": {
                "headers": headers,
                "total_records": len(content),
                "processing_method": "pattern_based_polars",
                "entity_type": plan.get("entity_type", "unknown"),
                "is_sample": False
            }
        }
    
    def _create_empty_result(self, message: str) -> Dict[str, Any]:
        """Create empty result response"""
        return {
            "display_type": "table",
            "content": [],
            "metadata": {
                "headers": [],
                "total_records": 0,
                "processing_method": "pattern_based_polars",
                "entity_type": "unknown",
                "is_sample": False,
                "message": message
            }
        }
    
    def _create_error_result(self, error: str) -> Dict[str, Any]:
        """Create error result response"""
        return {
            "display_type": "table",
            "content": [],
            "metadata": {
                "headers": [],
                "total_records": 0,
                "processing_method": "pattern_based_polars",
                "entity_type": "unknown",
                "is_sample": False,
                "error": error
            }
        }
