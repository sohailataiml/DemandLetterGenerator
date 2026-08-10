/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The API is a separate process; nothing is proxied or rewritten so the
  // browser talks to FastAPI directly and CORS stays explicit.
};

export default nextConfig;
