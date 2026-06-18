/** @type {import('next').NextConfig} */
const nextConfig = {
  // Self-contained server bundle for a small production Docker image.
  output: "standalone",
};

export default nextConfig;
