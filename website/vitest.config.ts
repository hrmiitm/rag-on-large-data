import {defineConfig} from 'vitest/config';import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],test:{environment:'jsdom',include:['tests/**/*.test.tsx'],setupFiles:['tests/setup.ts'],testTimeout:20000},define:{'import.meta.env.BASE_URL':JSON.stringify('/')}});
