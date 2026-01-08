import { createAppKit } from '@reown/appkit'
import { EthersAdapter } from '@reown/appkit-adapter-ethers'
import { arbitrum } from '@reown/appkit/networks'

// Config
const PROJECT_ID = '8c4d7a71e61c843b3b18a12fceaa3c02'

// State
let lastNonce = null
let signingMessage = null
let connectedAddress = null
let appKit = null

// DOM helpers
const $ = (s) => document.querySelector(s)
const showStatus = (msg, type) => {
  const box = $('#statusBox')
  box.textContent = msg
  box.className = 'status ' + type
}

// Fetch nonce on page load
async function fetchNonce() {
  try {
    const r = await fetch('/nonce')
    const j = await r.json()
    if (j.error) throw new Error(j.error)
    lastNonce = j.nonce
    signingMessage = j.message
    $('#message').value = j.message
    showStatus('Message loaded. Connect wallet to continue.', 'info')
  } catch (e) {
    showStatus('Failed to load message: ' + e.message, 'error')
  }
}

// Initialize AppKit
async function initAppKit() {
  const ethersAdapter = new EthersAdapter()

  appKit = createAppKit({
    adapters: [ethersAdapter],
    networks: [arbitrum],
    projectId: PROJECT_ID,
    metadata: {
      name: 'TreadFi',
      description: 'TreadFi Trading Login',
      url: window.location.origin,
      icons: ['https://tread.fi/favicon.ico']
    },
    features: {
      analytics: false,
      email: false,
      socials: false
    }
  })

  // Listen for account changes
  appKit.subscribeAccount((account) => {
    if (account.address) {
      onConnected(account.address)
    } else if (connectedAddress) {
      onDisconnected()
    }
  })
}

function onConnected(address) {
  connectedAddress = address
  $('#address').value = address
  $('#signBtn').disabled = !signingMessage
  $('#connectBtn').textContent = 'Connected'
  $('#connectBtn').disabled = true
  $('#disconnectBtn').classList.remove('hidden')
  showStatus('Wallet connected: ' + address, 'success')
}

function onDisconnected() {
  connectedAddress = null
  $('#address').value = ''
  $('#signBtn').disabled = true
  $('#connectBtn').textContent = 'Connect Wallet'
  $('#connectBtn').disabled = false
  $('#disconnectBtn').classList.add('hidden')
  showStatus('Wallet disconnected', 'info')
}

// Disconnect wallet
$('#disconnectBtn').onclick = async () => {
  try {
    if (appKit) {
      await appKit.disconnect()
    }
    onDisconnected()
  } catch (e) {
    showStatus('Disconnect failed: ' + e.message, 'error')
    console.error(e)
  }
}

// Connect wallet
$('#connectBtn').onclick = async () => {
  try {
    if (!appKit) {
      showStatus('Initializing...', 'info')
      await initAppKit()
    }
    appKit.open()
  } catch (e) {
    showStatus('Connect failed: ' + e.message, 'error')
    console.error(e)
  }
}

// Sign & login
$('#signBtn').onclick = async () => {
  try {
    if (!connectedAddress) {
      throw new Error('Connect wallet first')
    }
    if (!signingMessage || !lastNonce) {
      throw new Error('Message not loaded. Refresh the page.')
    }

    showStatus('Please sign in your wallet...', 'info')

    // Get provider and sign
    const provider = appKit.getWalletProvider()
    const signature = await provider.request({
      method: 'personal_sign',
      params: [signingMessage, connectedAddress]
    })

    showStatus('Submitting...', 'info')
    const r = await fetch('/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        address: connectedAddress,
        signature: signature,
        nonce: lastNonce
      })
    })

    const text = await r.text()
    if (!r.ok) throw new Error(text)

    showStatus('Login successful! You can close this tab.', 'success')
    $('#signBtn').disabled = true
  } catch (e) {
    showStatus('Failed: ' + e.message, 'error')
    console.error(e)
  }
}

// Init on load
fetchNonce()
initAppKit().catch(console.error)
