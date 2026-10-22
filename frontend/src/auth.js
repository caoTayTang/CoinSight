// Sign-in with Supabase (Google or GitHub). The project URL and publishable key come from the API at runtime
// (/v1/auth/config), so one build works with or without Supabase. The client library loads only when needed.
let clientPromise;

export function supabase() {
  clientPromise ??= fetch('/api/v1/auth/config')
    .then((r) => (r.ok ? r.json() : null))
    .then(async (config) => {
      if (!config?.url || !config?.publishable_key) return null;
      const { createClient } = await import('@supabase/supabase-js');
      const client = createClient(config.url, config.publishable_key, {
        auth: { flowType: 'pkce', detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
      });
      return { client, providers: config.providers || [] };
    })
    .catch(() => null);
  return clientPromise;
}

// The bearer token for the API, or null when signed out or when Supabase isn't configured.
export async function accessToken() {
  const auth = await supabase();
  if (!auth) return null;
  const { data } = await auth.client.auth.getSession();
  return data.session?.access_token || null;
}

export async function signIn(provider) {
  const auth = await supabase();
  await auth?.client.auth.signInWithOAuth({ provider, options: { redirectTo: window.location.origin + '/' } });
}

export async function signOut() {
  const auth = await supabase();
  await auth?.client.auth.signOut();
  window.dispatchEvent(new Event('coinsight-auth'));
}

// Components that show who is signed in listen for this event and re-read /v1/me.
export async function watchAuth() {
  const auth = await supabase();
  auth?.client.auth.onAuthStateChange((event) => {
    if (event === 'SIGNED_IN' || event === 'SIGNED_OUT') setTimeout(() => window.dispatchEvent(new Event('coinsight-auth')), 0);
  });
}
