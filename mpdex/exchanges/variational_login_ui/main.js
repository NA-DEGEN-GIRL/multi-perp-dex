import { createAppKit } from '@reown/appkit'
import { EthersAdapter } from '@reown/appkit-adapter-ethers'
import { arbitrum } from '@reown/appkit/networks'

// Config
const PROJECT_ID = '8c4d7a71e61c843b3b18a12fceaa3c02'

// State
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

// Initialize AppKit
async function initAppKit() {
  const ethersAdapter = new EthersAdapter()

  appKit = createAppKit({
    adapters: [ethersAdapter],
    networks: [arbitrum],
    projectId: PROJECT_ID,
    metadata: {
      name: 'Variational',
      description: 'Variational Perpetual Trading Login',
      url: window.location.origin,
      icons: ['https://variational.io/favicon.ico']
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
      // Was connected, now disconnected
      onDisconnected()
    }
  })
}

function onConnected(address) {
  connectedAddress = address
  $('#address').value = address
  $('#prepareBtn').disabled = false
  $('#connectBtn').textContent = 'Connected'
  $('#connectBtn').disabled = true
  $('#disconnectBtn').classList.remove('hidden')
  showStatus('Wallet connected: ' + address, 'success')
}

function onDisconnected() {
  connectedAddress = null
  signingMessage = null
  $('#address').value = ''
  $('#message').value = ''
  $('#prepareBtn').disabled = true
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

// Get message
$('#prepareBtn').onclick = async () => {
  try {
    if (!connectedAddress) {
      throw new Error('Connect wallet first')
    }
    showStatus('Fetching message...', 'info')
    const params = new URLSearchParams({ address: connectedAddress })
    const r = await fetch(`/signing-data?${params.toString()}`)
    const j = await r.json()
    if (j.error) throw new Error(j.error)
    signingMessage = j.message
    $('#message').value = j.message
    $('#signBtn').disabled = false
    showStatus('Ready to sign', 'success')
  } catch (e) {
    showStatus('Failed: ' + e.message, 'error')
  }
}

// Sign & login
$('#signBtn').onclick = async () => {
  try {
    if (!connectedAddress || !signingMessage) {
      throw new Error('Connect wallet and get message first')
    }

    const message = $('#message').value
    showStatus('Please sign in your wallet...', 'info')

    // Get provider and sign
    const provider = appKit.getWalletProvider()
    const signature = await provider.request({
      method: 'personal_sign',
      params: [message, connectedAddress]
    })

    showStatus('Submitting...', 'info')
    const r = await fetch('/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address: connectedAddress, signed_message: signature })
    })
    const j = await r.json()
    if (!j.ok) throw new Error(j.error || 'Login failed')

    showStatus('Login successful! You can close this tab.', 'success')
    $('#signBtn').disabled = true
  } catch (e) {
    showStatus('Failed: ' + e.message, 'error')
    console.error(e)
  }
}

// Init on load
initAppKit().catch(console.error)
