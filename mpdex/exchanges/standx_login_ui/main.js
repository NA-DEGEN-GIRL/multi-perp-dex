import { createAppKit } from '@reown/appkit'
import { EthersAdapter } from '@reown/appkit-adapter-ethers'
import { bsc } from '@reown/appkit/networks'

// Config
const PROJECT_ID = '8c4d7a71e61c843b3b18a12fceaa3c02'

// State
let signedData = null
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
    networks: [bsc],
    projectId: PROJECT_ID,
    metadata: {
      name: 'StandX Perps',
      description: 'StandX Perpetual Trading Login',
      url: window.location.origin,
      icons: ['https://standx.com/favicon.ico']
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
  signedData = null
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
    showStatus('Fetching message...', 'info')
    const r = await fetch('/prepare')
    const j = await r.json()
    if (!j.ok) throw new Error(j.error || 'Failed')
    signedData = j.signedData
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
    if (!connectedAddress || !signedData) {
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
      body: JSON.stringify({ signature, signedData })
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
