import React, { createContext, useState, useContext, useEffect } from 'react';
import config from '../config';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        checkAuth();
    }, []);

    const checkAuth = async () => {
        try {
            const response = await fetch(`${config.API_URL}/auth/me`, {
                headers: {
                    'Content-Type': 'application/json',
                },
                // Credentials include cookies
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                setUser(data);
            } else {
                setUser(null);
            }
        } catch (error) {
            console.error("Auth check failed", error);
            setUser(null);
        } finally {
            setLoading(false);
        }
    };

    const login = async (username, password) => {
        try {
            console.log("Attempting login for:", username);
            const response = await fetch(`${config.API_URL}/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
                credentials: 'include'
            });

            console.log("Login response status:", response.status);

            if (response.ok) {
                const data = await response.json();
                console.log("Login success data:", data);
                setUser({ username: data.username });
                return { success: true };
            } else {
                const errorData = await response.json();
                console.error("Login failed:", errorData);
                return { success: false, message: errorData.error || 'Login failed' };
            }
        } catch (error) {
            console.error("Login network error:", error);
            return { success: false, message: 'Network error. Check console.' };
        }
    };

    const register = async (username, password) => {
        try {
            const response = await fetch(`${config.API_URL}/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                if (data.username) {
                    setUser({ username: data.username });
                }
                return true;
            }
            return false;
        } catch (error) {
            console.error("Registration failed", error);
            return false;
        }
    };

    const logout = async () => {
        await fetch(`${config.API_URL}/auth/logout`, {
            method: 'POST',
            credentials: 'include'
        });
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, login, register, logout, loading }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
