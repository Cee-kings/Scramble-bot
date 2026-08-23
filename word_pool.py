"""Built-in word pool for Scramble-bot.

The pool is kept outside bot.py so the game logic stays easy to maintain.
Crypto terms are intentionally included alongside general vocabulary.
"""

CRYPTO_WORDS = """
bitcoin satoshi blockchain ethereum ether solana cardano polkadot avalanche
polygon cosmos algorand litecoin dogecoin ripple stellar monero tether usdcoin
binance coinbase kraken kucoin wallet ledger trezor metamask phantom exodus
token coin altcoin stablecoin memecoin shitcoin utility governance security
nonfungible nft defi dao dex swap liquidity farming staking mining validator
miner hash hashing nonce block reward halving merkle genesis address publickey
privatekey seedphrase passphrase signature multisig custodial custody exchange
onchain offchain mainnet testnet sidechain rollup channel bridge oracle
smartcontract protocol consensus proof stake work authority history capacity
layerzero layerone layertwo gas fee wei gwei satoshi wei transaction mempool
node nodeoperator validator delegator delegation yield apr apy collateral
leverage liquidation borrow lending lendingpool flashloan arbitrage slippage
impermanent loss pool reserve pair router factory vault treasury emissions
airdrop allocation vesting presale crowdsale launchpad whitepaper roadmap
hardfork softfork upgrade governance proposal snapshot quorum validator
cryptography encryption decryption cipher ciphertext plaintext entropy random
elliptic curve cryptanalysis zero knowledge zkproof snark stark commitment
rollup sequencer optimistic fraudproof validityproof sidechain parachain
substrate cosmos sdk tendermint solana program evm virtualmachine bytecode
opcode compiler contract abi rpc endpoint websocket indexer subgraph
chainlink uniswap aave compound maker curve sushi avalanche arbitrum optimism
base scroll linea zksync near tezos tron eos vechain hedera filecoin theta
render chain tokenomics tokenization fractionalization rwa metaverse webthree
gamefi socialfi fan token inscription ordinal rune inscription digitalasset
marketcap volume supply circulation liquidity volatility bullish bearish
support resistance breakout candle chart candlestick portfolio investment
trading trader holder whale shark shrimp degen hodler maximalist validator
recovery backup phishing scam fraud exploit attack audit bug bounty reentrancy
sybil sandwich front running frontrunning mev censorship permissionless
decentralized centralized transparent immutable trustless pseudonymous
""".split()

# Common roots make useful word variants without requiring a large dependency
# or an external dictionary at runtime.
WORD_ROOTS = """
able about above accept access account across action active actor actual adapt
addition address adjust admire admit advance advice affect afford afraid after
again agent agree ahead alarm album alert alive allow almost alone along alter
amazing amount ancient angle angry animal answer appear apple apply april area
argue arise army around arrange arrive article artist aspect assist assume
attack attend august author average avoid awake award aware balance bakery
balloon banana banner barely bargain basket battery beach beauty because become
before begin behave behind believe belong below benefit beside better between
beyond bicycle biology blanket blossom border bottle branch brave bread breeze
bridge bright bring broad broken brother budget build busy butter button cabin
camera campaign cancel cancer candle capable capital captain capture carbon
career careful carpet carry castle casual cause celebrate center central century
certain chair chance change charge charity charm cheap check cheese cherry
choice choose circle citizen city claim class clean clear clever climate climb
clock close cloud coach coast coffee collect college color column combine comedy
comfort command common company compare compete complete complex concern concert
conduct connect consider consist contact contain content contest continue control
convert cookie copper corner correct courage course cousin cover create credit
crystal culture curious current custom cycle daily damage danger dance daughter
debate decide declare decline decorate defend define degree deliver demand depend
describe desert design desire detail develop device diamond differ dinner direct
discover discuss disease display distance divide doctor document dolphin double
dragon drama dream dress drift driver during early earth eastern easy edition
educate effect effort either elder electric element eleven emerge emotion employ
enable encounter energy engine enjoy enough ensure enter entire equal escape
estate event exact example excited exercise exist expand expect expense explain
explore express extend extra fabric factor family famous farmer fashion feature
federal feeling female festival fiction field figure final finance finger finish
firefly first fitness flame flight flower fluid focus follow forest forever
formal fortune forward founder fragile freedom fresh friend frontier frozen fruit
future galaxy garden garlic gather general gentle genuine geography gesture
giant gift ginger glacier global glory golden govern graceful gradual grammar
grand grant grape graphic grass grateful green ground group growth guard guitar
habit hammer handle happen harbor harmony harvest hazard health healthy hearing
heart heaven heavy helpful history holiday honest honey honor hopeful horse
hospital human humble humor hundred hunger hunter hurry ideal identify ignore
image imagine impact improve include income increase indeed index industry infant
inform initial injury inside inspire install instant instead interest invite
island issue jacket jewel journey judge jungle justice keyboard kidney kindness
kingdom kitchen kitten knowledge label language laptop large laugh leader learn
leather leave lecture legal legend leisure lemon length lesson letter library
license lighten limit liquid listen little lively local logic lonely lovely
lucky machine magic magnet major manage manner market marriage master matter
maximum meadow measure media medical meeting memory mental message middle mighty
million mineral minute miracle mobile model modern modest moment monitor monthly
morning mountain mouse movie museum music mystery narrow nation native nature
nearby nearly necessary neck needle neighbor nervous network never notice number
object observe obvious ocean office offer effort option orange order ordinary
organize original outside package palace parent park partner party patient pattern
peace people perfect perhaps period permit person picture pioneer planet plastic
player pleasant plenty pocket popular portion practice prepare present prevent
private problem process produce product profile promise protect proud provide
public pumpkin purpose puzzle quality quarter question quick quiet rabbit random
rapid rather reach reader reason receive recent recipe record recover recycle
reduce reflect regular relation relax release relief remain remember remove
repair repeat replace report request rescue research resolve resource respect
result return reveal rhythm ribbon river rocket routine royal rubber rugged
salad salary sample satisfy science screen search season second secret secure
select senior sense series service settle shadow share shelter shift shiny
shoulder signal silver simple sister skill sleep smart smooth society soldier
solution source space speak special speech spirit spring square stable station
status steady steel stick still stone storm story strategy street strong student
studio subject success sudden summer supply support surface surprise survive
symbol system tablet talent target teacher team temple tender tennis theory
thick thing thought thunder ticket tidy tiger timber tiny today together tomato
tonight travel treasure treat triangle trick triumph trouble tunnel turtle twelve
unique universe update useful valley value vehicle velvet version video village
violet virtual vision visit voice volume voyage wagon wander warning water
wealth weather weekend welcome western whale window winter wisdom wonder wooden
worker world writer yellow young zebra zero adventure champion victory
""".split()

# Inflections are deliberately limited to simple, recognizable forms. The
# resulting set is large enough for long-running challenges without repeats.
INFLECTIONS = ("", "s", "ed", "ing", "er", "ly", "ness", "ful", "less", "ment")

GENERATED_WORDS = [
    f"{root}{ending}"
    for root in WORD_ROOTS
    for ending in INFLECTIONS
    if len(root) >= 3 and len(root + ending) <= 18
]

DEFAULT_WORDS = sorted(set(CRYPTO_WORDS + GENERATED_WORDS))

if len(DEFAULT_WORDS) <= 2000:
    raise RuntimeError(f"Built-in word pool must contain over 2,000 words, got {len(DEFAULT_WORDS)}")