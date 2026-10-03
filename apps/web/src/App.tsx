import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, Route, Routes } from 'react-router';

import { api } from './api/client';
import { RegisterPage, SignInPage } from './auth/pages';
import { ME_KEY, useMe } from './auth/useMe';

function Home() {
  const me = useMe();
  const queryClient = useQueryClient();
  const signOut = useMutation({
    mutationFn: () => api<void>('/auth/logout', { method: 'POST' }),
    onSuccess: () => queryClient.setQueryData(ME_KEY, null),
  });

  return (
    <main className="mx-auto max-w-3xl p-6">
      <h1 className="text-3xl font-semibold">ListenUp</h1>
      <p className="mt-2">Practise English listening, one clip at a time.</p>
      {me.data ? (
        <div className="mt-6 flex items-center gap-4">
          <p>Signed in as {me.data.email}</p>
          <button
            type="button"
            onClick={() => signOut.mutate()}
            className="rounded border border-gray-400 px-3 py-1 focus:outline-2 focus:outline-offset-2 focus:outline-blue-700"
          >
            Sign out
          </button>
        </div>
      ) : me.isSuccess ? (
        <p className="mt-6 flex gap-4">
          <Link to="/sign-in" className="text-blue-700 underline">
            Sign in
          </Link>
          <Link to="/register" className="text-blue-700 underline">
            Create an account
          </Link>
        </p>
      ) : null}
    </main>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/sign-in" element={<SignInPage />} />
      <Route path="/register" element={<RegisterPage />} />
    </Routes>
  );
}
