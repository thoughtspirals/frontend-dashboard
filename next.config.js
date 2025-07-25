/** @type {import('next').NextConfig} */
const nextConfig = {
  webpack: (config, { isServer }) => {
    // Monaco Editor webpack config
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
        "monaco-editor": false,
      }
    }
    return config
  },
  async rewrites() {
    return [
      {
        source: '/api/dashboard/:path*',
        ppdestination: 'http://127.0.0.1:8000/api/dashboard/:path*',
      },
      {
        source: '/api/hardware/:path*',
        destination: 'http://127.0.0.1:8000/api/hardware/:path*',
      },
      {
        source: '/api/io/polled-values',
        destination: 'http://127.0.0.1:8000/deploy/api/io/polled-values',
      },
    ]
  },
}

module.exports = nextConfig
