import urlparse
import os, sys, re, random, pybitcointools, bitcoinrpc, math
from decimal import Decimal
from msc_apps import *
from blockchain_utils import *
import config

class OmniTransaction:
    confirm_target=6
    HEXSPACE_SECOND='21'
    mainnet_exodus_address='1EXoDusjGwvnjZUyKkxZ4UHEf77z6A5S4P'
    testnet_exodus_address='mpexoDuSkGGqvqrkrjiFng38QPkJQVFyqv'

    def __init__(self,tx_type,form):
        self.conn = getRPCconn()
        self.testnet = False
        self.magicbyte = 0
        self.exodus_address=self.mainnet_exodus_address

        if 'testnet' in form and ( form['testnet'] in ['true', 'True'] ):
            self.testnet =True
            self.magicbyte = 111
            self.exodus_address=self.testnet_exodus_address

        try:
          if config.D_PUBKEY and ( 'donate' in form ) and ( form['donate'] in ['true', 'True'] ):
            print "We're Donating to pubkey for: "+pybitcointools.pubkey_to_address(config.D_PUBKEY)
            self.pubkey = config.D_PUBKEY
          else:
            print "not donating"
            self.pubkey = form['pubkey']
        except NameError, e:
          print e
          self.pubkey = form['pubkey']
        self.fee = estimateFee(self.confirm_target)['result']
        self.rawdata = form
        self.tx_type = tx_type

    def get_unsigned(self):
        # get payload
        payload = self.__generate_payload()
        # Add exodous output
        rawtx = None
        if 'transaction_to' in self.rawdata:
            # Add reference for reciever
            rawtx = createrawtx_reference(self.rawdata['transaction_to'], rawtx)['result']

        # Add the payload    
        if len(payload) <= 152:  #80bytes - 4 bytes for omni marker
            rawtx = createrawtx_opreturn(payload, rawtx)['result']
        else:
            rawtx = createrawtx_multisig(payload, self.rawdata['transaction_from'], self.pubkey, rawtx)['result']

        # Decode transaction to get total needed amount
        decodedtx = decoderawtransaction(rawtx)['result']

        # Sumup the outputs
        fee_total = Decimal(self.fee)
        for output in decodedtx['vout']:
            fee_total += Decimal(output['value'])

        fee_total_satoshi = int( round( fee_total * Decimal(1e8) ) )

        # Get utxo to generate inputs
        print "Calling bc_getutxo with ", self.rawdata['transaction_from'], fee_total_satoshi
        dirty_txes = bc_getutxo( self.rawdata['transaction_from'], fee_total_satoshi )
        print "received", dirty_txes

        if (dirty_txes['error'][:3]=='Con'):
            raise Exception({ "status": "NOT OK", "error": "Couldn't get list of unspent tx's. Response Code: " + dirty_txes['code']  })

        if (dirty_txes['error'][:3]=='Low'):
            raise Exception({ "status": "NOT OK", "error": "Not enough funds, try again. Needed: " + str(fee_total) + " but Have: " + dirty_txes['avail']  })

        total_amount = dirty_txes['avail']
        unspent_tx = dirty_txes['utxos']

        change = total_amount - fee_total_satoshi

        #DEBUG 
        print [ "Debugging...", dirty_txes,"miner fee sats: ", self.fee, "change: ",change,"total_amt: ", total_amount,"fee tot sat: ", fee_total_satoshi,"utxo ",  unspent_tx,"to ", self.rawdata['transaction_to'] ]

        #source script is needed to sign on the client credit grazcoin
        hash160=bc_address_to_hash_160(self.rawdata['transaction_from']).encode('hex_codec')
        prevout_script='OP_DUP OP_HASH160 ' + hash160 + ' OP_EQUALVERIFY OP_CHECKSIG'

        validnextinputs = []   #get valid redeemable inputs
        for unspent in unspent_tx:
            #retrieve raw transaction to spend it
            prev_tx = getrawtransaction(unspent[0])['result']

            for output in prev_tx['vout']:
                if 'reqSigs' in output['scriptPubKey'] and output['scriptPubKey']['reqSigs'] == 1 and output['scriptPubKey']['type'] != 'multisig':
                    for address in output['scriptPubKey']['addresses']:
                        if address == self.rawdata['transaction_from'] and int(output['n']) == int(unspent[1]):
                            validnextinputs.append({ "txid": prev_tx['txid'], "vout": output['n'], "scriptPubKey" : output['scriptPubKey']['hex'], "value" : output['value']})
                            break
        # Add the inputs
        for input in validnextinputs:
            rawtx = createrawtx_input(input['txid'],input['vout'],rawtx)['result']

        # Add the change
        rawtx = createrawtx_change(rawtx, validnextinputs, self.rawdata['transaction_from'], float(fee_total))['result']

        return { 'status':200, 'unsignedhex': rawtx , 'sourceScript': prevout_script }

    def __generate_payload(self):
        if self.tx_type == 0:
            return getsimplesendPayload(self.rawdata['currency_identifier'], self.rawdata['amount_to_transfer'])['result']
        if self.tx_type == 20:
            return getdexsellPayload(self.rawdata['currency_identifier'], self.rawdata['amount_for_sale'], self.rawdata['amount_desired'], self.rawdata['blocks'], self.rawdata['min_buyer_fee'], self.rawdata['action'])['result']
        if self.tx_type == 22:
            return getdexacceptPayload(self.rawdata['currency_identifier'], self.rawdata['amount'])['result']
        if self.tx_type == 50:
            return getissuancefixedPayload(self.rawdata['ecosystem'],self.rawdata['property_type'],self.rawdata['previous_property_id'],self.rawdata['property_category'],self.rawdata['property_subcategory'],self.rawdata['property_name'],self.rawdata['property_url'],self.rawdata['property_data'],self.rawdata['number_properties'])['result']
        if self.tx_type == 51:
            return getissuancecrowdsalePayload(self.rawdata['ecosystem'],self.rawdata['property_type'],self.rawdata['previous_property_id'],self.rawdata['property_category'],self.rawdata['property_subcategory'],self.rawdata['property_name'],self.rawdata['property_url'],self.rawdata['property_data'],self.rawdata['currency_identifier_desired'],self.rawdata['number_properties'], self.rawdata['deadline'], self.rawdata['earlybird_bonus'], self.rawdata['percentage_for_issuer'])['result']
        if self.tx_type == 54:
            return getissuancemanagedPayload(self.rawdata['ecosystem'],self.rawdata['property_type'],self.rawdata['previous_property_id'],self.rawdata['property_category'],self.rawdata['property_subcategory'],self.rawdata['property_name'],self.rawdata['property_url'],self.rawdata['property_data'])['result']
        if self.tx_type == 55:
            return getgrantPayload(self.rawdata['currency_identifier'], self.rawdata['amount'], self.rawdata['memo'])['result']
        if self.tx_type == 56:
            return getrevokePayload(self.rawdata['currency_identifier'], self.rawdata['amount'], self.rawdata['memo'])['result']