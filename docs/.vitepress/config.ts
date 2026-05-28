import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'zenit',
  description: 'Scaffold Python projects without lock-in',
  base: '/zenit/docs/',
  cleanUrls: true,

  themeConfig: {
    logo: { text: 'zenit' },

    nav: [
      { text: 'Home', link: 'https://bojankonjevic.github.io/zenit/' },
      { text: 'Configure', link: 'https://bojankonjevic.github.io/zenit/configure/' },
      { text: 'GitHub', link: 'https://github.com/BojanKonjevic/zenit' },
    ],

    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Introduction', link: '/getting-started' },
          { text: 'Configuration', link: '/configuration' },
        ],
      },
      {
        text: 'Architecture',
        collapsed: false,
        items: [
          { text: 'Overview', link: '/architecture/' },
          { text: 'The Manifest', link: '/architecture/manifest' },
          { text: 'Code Injection', link: '/architecture/injection' },
          { text: 'Addons & Templates', link: '/architecture/addons-and-templates' },
        ],
      },
      {
        text: 'Commands',
        collapsed: false,
        items: [
          { text: 'Overview', link: '/commands/' },
          { text: 'zenit create', link: '/commands/create' },
          { text: 'zenit migrate', link: '/commands/migrate' },
          { text: 'zenit add', link: '/commands/add' },
          { text: 'zenit remove', link: '/commands/remove' },
          { text: 'zenit doctor', link: '/commands/doctor' },
          { text: 'zenit list', link: '/commands/list' },
          { text: 'zenit graph', link: '/commands/graph' },
          { text: 'zenit config', link: '/configuration' },
        ],
      },
      {
        text: 'Templates',
        collapsed: false,
        items: [
          { text: 'Overview', link: '/templates/' },
          { text: 'blank', link: '/templates/blank' },
          { text: 'fastapi', link: '/templates/fastapi' },
          { text: 'Writing Your Own', link: '/templates/writing-templates' },
        ],
      },
      {
        text: 'Addons',
        collapsed: false,
        items: [
          { text: 'Overview', link: '/addons/' },
          { text: 'auth-manual', link: '/addons/auth-manual' },
          { text: 'celery', link: '/addons/celery' },
          { text: 'docker', link: '/addons/docker' },
          { text: 'github-actions', link: '/addons/github-actions' },
          { text: 'postgres', link: '/addons/postgres' },
          { text: 'redis', link: '/addons/redis' },
          { text: 'sentry', link: '/addons/sentry' },
          { text: 'sqlalchemy', link: '/addons/sqlalchemy' },
          { text: 'sqlmodel', link: '/addons/sqlmodel' },
          { text: 'Writing Your Own', link: '/addons/writing-addons' },
        ],
      },
      {
        text: 'Contributing',
        items: [
          { text: 'Contributing Guide', link: '/contributing' },
        ],
      },
    ],

    search: {
      provider: 'local',
    },

    editLink: {
      pattern: 'https://github.com/BojanKonjevic/zenit/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },

    footer: {
      message: 'Released under the <a href="https://github.com/BojanKonjevic/zenit/blob/main/LICENSE">MIT License</a>.',
      copyright: 'Copyright © 2024–present zenit contributors',
    },
  },

  markdown: {
    theme: {
      light: 'github-light',
      dark: 'github-dark',
    },
  },

  vite: {
    build: {},
  },
})
