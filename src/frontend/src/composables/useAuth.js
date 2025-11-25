import { ref, readonly } from "vue";
import { useRouter } from "vue-router";

// Create reactive state (only initialized once)
const user = ref(null);
const isAuthenticated = ref(false);
const initialized = ref(false);
const needsSetup = ref(false);
const setupChecked = ref(false);
const error = ref(null);
const loading = ref(false);

// Computed values
const username = () => user.value?.username || "";
const isAdmin = () => user.value?.role === "admin";

// Export auth composable
export function useAuth() {
    const router = useRouter();

    // Handle API responses and errors consistently
    // Also update the handleResponse function to handle these complex errors better:
    const handleResponse = async (response) => {
        // Handle session timeout (401)
        if (response.status === 401) {
            isAuthenticated.value = false;
            user.value = null;
            if (router) {
                router.push('/login');
            } else {
                window.location.href = '/login';
            }
            throw new Error("Session expired");
        }

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));

            if (errorData.detail && Array.isArray(errorData.detail)) {
                throw new Error(errorData.detail.map((err) => err.msg).join(", "));
            } else if (errorData.detail && typeof errorData.detail === "string") {
                throw new Error(errorData.detail);
            } else {
                throw new Error(`HTTP error ${response.status}`);
            }
        }
        return response.json();
    };

    // Auth actions
    const checkSetupStatus = async () => {
        try {
            const response = await fetch("/api/auth/setup-status");
            const data = await handleResponse(response);
            needsSetup.value = data.needs_setup;
            setupChecked.value = true;
        } catch (err) {
            console.error("Failed to check setup status:", err);
        }
    };

    const checkAuth = async () => {
        loading.value = true;
        error.value = null;

        try {
            const response = await fetch("/api/auth/me");
            if (response.ok) {
                user.value = await response.json();
                isAuthenticated.value = true;
            } else {
                isAuthenticated.value = false;
                user.value = null;
            }
        } catch (err) {
            isAuthenticated.value = false;
            user.value = null;
        } finally {
            initialized.value = true;
            loading.value = false;
        }
    };

    const login = async (username, password) => {
        loading.value = true;
        error.value = null;

        try {
            // FastAPI expects form data for OAuth2 password flow
            const formData = new URLSearchParams();
            formData.append("username", username);
            formData.append("password", password);

            const loginResponse = await fetch("/api/auth/login", {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: formData,
            });

            if (!loginResponse.ok) {
                const errorData = await loginResponse.json().catch(() => ({}));

                // Handle complex validation errors from FastAPI
                if (errorData.detail && Array.isArray(errorData.detail)) {
                    // Extract messages from validation errors
                    error.value = errorData.detail.map((err) => err.msg).join(", ");
                } else if (errorData.detail && typeof errorData.detail === "string") {
                    // Simple string error
                    error.value = errorData.detail;
                } else {
                    // Fallback error message
                    error.value = `Login failed: ${loginResponse.status}`;
                }
                return false;
            }

            // If successful, get user info
            const userResponse = await fetch("/api/auth/me");
            if (userResponse.ok) {
                user.value = await userResponse.json();
                isAuthenticated.value = true;
                return true;
            } else {
                error.value = "Failed to get user info after login";
                return false;
            }
        } catch (err) {
            error.value = err.message || "Failed to login";
            isAuthenticated.value = false;
            user.value = null;
            return false;
        } finally {
            loading.value = false;
        }
    };

    const setupAdmin = async (username, password) => {
        loading.value = true;
        error.value = null;

        try {
            const response = await fetch("/api/auth/setup", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    username,
                    password,
                }),
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));

                // Handle complex validation errors from FastAPI
                if (errorData.detail && Array.isArray(errorData.detail)) {
                    // Extract messages from validation errors
                    error.value = errorData.detail.map((err) => err.msg).join(", ");
                } else if (errorData.detail && typeof errorData.detail === "string") {
                    // Simple string error
                    error.value = errorData.detail;
                } else {
                    // Fallback error message
                    error.value = `Setup failed: ${response.status}`;
                }
                return false;
            }

            // If successful, get user info
            const userResponse = await fetch("/api/auth/me");
            if (userResponse.ok) {
                user.value = await userResponse.json();
                isAuthenticated.value = true;
                needsSetup.value = false;
                return true;
            } else {
                error.value = "Failed to get user info after setup";
                return false;
            }
        } catch (err) {
            error.value = err.message || "Failed to setup admin user";
            return false;
        } finally {
            loading.value = false;
        }
    };

    const logout = async () => {
        try {
            await fetch("/api/auth/logout");
        } catch (err) {
            console.error("Error during logout:", err);
        } finally {
            // Always reset auth state locally
            user.value = null;
            isAuthenticated.value = false;
        }
    };

    return {
        // State (readonly to prevent mutation from outside)
        user: readonly(user),
        isAuthenticated: readonly(isAuthenticated),
        initialized: readonly(initialized),
        needsSetup: readonly(needsSetup),
        setupChecked: readonly(setupChecked),
        error: readonly(error),
        loading: readonly(loading),

        // Computed values
        username,
        isAdmin,

        // Actions
        checkSetupStatus,
        checkAuth,
        login,
        setupAdmin,
        logout,
    };
}
