package com.obieda.fulfillos.data

import com.obieda.fulfillos.domain.SessionInfo

class SessionManager(
    private val api: ApiClient,
    private val secureStore: SecureSessionStore,
    val deviceId: String,
    private val appVersion: String,
) {
    @Volatile
    var current: SessionInfo? = null
        private set

    fun loginBlocking(username: String, password: String): Result<SessionInfo> = runCatching {
        val response = api.login(username.trim(), password, deviceId, appVersion)
        if (!response.ok) error("Login failed (${response.code})")
        establish(api.parseSession(response.body))
    }

    fun recoverBlocking(): Result<SessionInfo?> = runCatching {
        val refresh = secureStore.getRefreshToken() ?: return@runCatching null
        val storedDevice = secureStore.getDeviceId()
        if (storedDevice != null && storedDevice != deviceId) {
            secureStore.clear()
            return@runCatching null
        }
        val response = api.refresh(refresh, deviceId)
        if (!response.ok) {
            secureStore.clear()
            return@runCatching null
        }
        establish(api.parseSession(response.body))
    }

    fun refreshBlocking(): Boolean {
        val refresh = secureStore.getRefreshToken() ?: return false
        val response = runCatching { api.refresh(refresh, deviceId) }.getOrNull() ?: return false
        if (!response.ok) {
            if (response.code == 401) logout()
            return false
        }
        return runCatching {
            establish(api.parseSession(response.body))
            true
        }.getOrDefault(false)
    }

    fun logout() {
        current = null
        api.accessToken = null
        secureStore.clear()
    }

    private fun establish(session: SessionInfo): SessionInfo {
        current = session
        api.accessToken = session.accessToken
        secureStore.putSession(session.refreshToken, session.username, deviceId)
        return session
    }
}
