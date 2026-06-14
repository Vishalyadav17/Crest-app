/**
 * state.js — Central application state for Crest
 * Replaces window._foo globals scattered across modules.
 */
const state = {
  modules: {
    m4Loaded:    false,
    allocLoaded: false,
    mfLoaded:    false,
  },
  privacy: localStorage.getItem('privacy') === '1',
  user: {
    id: null,
    email: null,
  },
};

window.state = state;
