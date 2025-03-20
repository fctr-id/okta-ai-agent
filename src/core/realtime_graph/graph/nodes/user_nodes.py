from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
from pydantic_graph import BaseNode, End, GraphRunContext

from src.core.realtime_graph.graph.state import OktaState
from src.core.realtime_graph.graph.deps import OktaDeps
from src.core.realtime.agents.coding_agent import coding_agent  # Import existing coding agent

@dataclass
class SearchUsers(BaseNode[OktaState, OktaDeps]):
    """
    Search for users in Okta based on search expressions or filter criteria.
    
    This node allows you to search for users by their profile attributes (first name, 
    last name, email, etc.), status, custom attributes, or any other supported Okta user property.
    
    ## Search Parameters
    
    ### search (Recommended)
    - Powerful and flexible filtering
    - Uses SCIM filter syntax (e.g., `profile.department eq "Engineering" and status eq "ACTIVE"`)
    - Supports operators: eq, ge, gt, le, lt, sw, co, pr, and, or
    - Filters on most user properties, including custom ones, id, status, dates, and arrays
    
    ### filter (Limited)
    - Simpler filtering, but less powerful than search
    - Supports only eq (except for lastUpdated, which allows date comparisons)
    - Filters on: status, lastUpdated, id, profile.login, profile.email, profile.firstName, profile.lastName
    
    ### q (Simple Lookup)
    - Basic lookup, limited functionality
    - Searches firstName, lastName, email (startsWith)
    - Not recommended for precise searches
    
    Parameters:
    -----------
    natural_language_query: str (optional)
        Natural language description of the search you want to perform
        Example: "Find all users with first name Noah"
        
    search_query: str (optional)
        Search expression for filtering users by their attributes
        Example: 'profile.firstName eq "John"'
        
    filter_query: str (optional)
        Filter expression for filtering users
        Example: 'status eq "ACTIVE"'
        
    limit: int
        Maximum number of results to return (default: 200, max: 200)
    
    Returns:
    --------
    List of user objects containing profile information and system attributes
    
    Examples:
    ---------
    1. Using natural language:
       ```
       SearchUsers(natural_language_query="Find all users with first name Noah")
       ```
       
    2. Find users with first name "John":
       ```
       SearchUsers(search_query='profile.firstName eq "John"')
       ```
    
    3. Find active users with last name "Smith":
       ```
       SearchUsers(
           search_query='profile.lastName eq "Smith" and status eq "ACTIVE"'
       )
       ```
       
    4. Find users with company email domain:
       ```
       SearchUsers(search_query='profile.email sw "user@example.com"')
       ```
       
    5. Find users with multiple conditions using OR:
       ```
       SearchUsers(search_query='profile.city eq "San Francisco" or profile.city eq "London"')
       ```
    
    6. Find users in Engineering department who are active:
       ```
       SearchUsers(search_query='profile.department eq "Engineering" and status eq "ACTIVE"')
       ```
       
    7. Find users updated after a specific date:
       ```
       SearchUsers(filter_query='lastUpdated gt "2024-01-01T00:00:00.000Z"')
       ```
       
    8. Find users with a specific custom attribute:
       ```
       SearchUsers(search_query='profile.employeeNumber eq "12345"')
       ```
       
    9. Find users who have a particular attribute defined (present):
       ```
       SearchUsers(search_query='profile.employeeNumber pr')
       ```
       
    10. Limit results to 50 users:
        ```
        SearchUsers(search_query='profile.firstName sw "J"', limit=50)
        ```
    """
    # Input parameters
    natural_language_query: Optional[str] = None
    search_query: Optional[str] = None
    filter_query: Optional[str] = None
    limit: int = 200
    
    # Store agent messages for context
    agent_messages: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    
    # Documentation for this node
    docstring_notes = True
    
    async def run(
        self, 
        ctx: GraphRunContext[OktaState, OktaDeps]
    ) -> End[List[Dict]]:
        """Search for users in Okta using search or filter query."""
        # If natural language query is provided, use coding agent to generate query
        if self.natural_language_query and not self.search_query:
            ctx.deps.logger.info(f"[{ctx.deps.query_id}] Converting natural query: {self.natural_language_query}")
            
            prompt = f"""
            Generate an Okta search query for the following request:
            "{self.natural_language_query}"
            
            Return just the search query string that would be passed to the search_query parameter.
            For example: profile.firstName eq "John"
            
            Do not include any other code or explanations, only the query string.
            """
            
            # Use existing coding agent
            result = await coding_agent.generate_code(
                prompt=prompt,
                context={},
                query_id=ctx.deps.query_id
            )
            
            # Extract the query from result
            self.search_query = result.strip().strip('"\'')  # Remove quotes
            
            ctx.deps.logger.info(
                f"[{ctx.deps.query_id}] Generated search query: '{self.search_query}'"
            )
        
        # Log the operation
        ctx.deps.logger.info(f"[{ctx.deps.query_id}] Searching users with query: {self.search_query}")
        
        # Build query parameters
        query_params = {}
        if self.search_query:
            query_params["search"] = self.search_query
        if self.filter_query:
            query_params["filter"] = self.filter_query
        if self.limit:
            query_params["limit"] = self.limit
            
        try:
            # Execute the API call
            users, resp, err = await ctx.deps.client.list_users(query_params=query_params)
            
            if err:
                error_msg = f"Error listing users: {str(err)}"
                ctx.state.errors.append(error_msg)
                ctx.deps.logger.error(f"[{ctx.deps.query_id}] {error_msg}")
                return End({"error": error_msg})
                
            # Process results
            ctx.state.users_list = [user.as_dict() for user in users]
            ctx.deps.logger.info(f"[{ctx.deps.query_id}] Found {len(ctx.state.users_list)} users")
            
            # Store result in state
            ctx.state.result = ctx.state.users_list
            return End(ctx.state.users_list)
                
        except Exception as e:
            error_msg = f"Exception in SearchUsers: {str(e)}"
            ctx.state.errors.append(error_msg)
            ctx.deps.logger.error(f"[{ctx.deps.query_id}] {error_msg}", exc_info=True)
            return End({"error": error_msg})


@dataclass
class GetUserDetails(BaseNode[OktaState, OktaDeps]):
    """
    Get detailed information about a specific user by ID.
    
    This node retrieves comprehensive information about a user, including:
    - Complete profile data (firstName, lastName, email, etc.)
    - Status information (ACTIVE, DEPROVISIONED, etc.)
    - System data (creation date, last login, etc.)
    - Credential information
    
    Parameters:
    -----------
    user_id: str (required)
        The Okta user ID to retrieve details for
        Format: 00u1qqxky9bSoOazk0h7 (string)
    
    Returns:
    --------
    Detailed user object with complete profile and system information
    
    Examples:
    ---------
    1. Get user details by ID directly:
       ```
       GetUserDetails(user_id="00u1qqxky9bSoOazk0h7")
       ```
    
    2. Get user details after performing a search:
       ```
       # After SearchUsers has populated users_list in state
       GetUserDetails(user_id=state.users_list[0]["id"])
       ```
    """
    # Input parameters
    user_id: str
    
    # Documentation
    docstring_notes = True
    
    async def run(
        self, 
        ctx: GraphRunContext[OktaState, OktaDeps]
    ) -> End[Dict]:
        """Retrieve detailed information about a specific user by ID."""
        # Log the operation
        ctx.deps.logger.info(f"[{ctx.deps.query_id}] Getting user details for: {self.user_id}")
        
        try:
            # Execute API call
            user, resp, err = await ctx.deps.client.get_user(self.user_id)
            
            if err:
                error_msg = f"Error getting user: {str(err)}"
                ctx.state.errors.append(error_msg)
                ctx.deps.logger.error(f"[{ctx.deps.query_id}] {error_msg}")
                return End({"error": error_msg})
                
            # Process results
            ctx.state.user_details = user.as_dict()
            ctx.deps.logger.info(f"[{ctx.deps.query_id}] Successfully retrieved user details")
            
            # Store result in state
            ctx.state.result = ctx.state.user_details
            return End(ctx.state.user_details)
                
        except Exception as e:
            error_msg = f"Exception in GetUserDetails: {str(e)}"
            ctx.state.errors.append(error_msg)
            ctx.deps.logger.error(f"[{ctx.deps.query_id}] {error_msg}", exc_info=True)
            return End({"error": error_msg})