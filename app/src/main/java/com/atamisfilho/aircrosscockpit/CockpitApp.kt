package com.atamisfilho.aircrosscockpit

import android.app.Application

/**
 * Application base. Mantém referências globais leves do app.
 */
class CockpitApp : Application() {
    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    companion object {
        @Volatile
        private var instance: CockpitApp? = null

        /** Instância global (usada por singletons sem contexto próprio). */
        fun get(): CockpitApp = requireNotNull(instance) {
            "CockpitApp não foi criado ainda"
        }
    }
}
